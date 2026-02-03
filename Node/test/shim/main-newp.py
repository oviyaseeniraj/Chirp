import os
import time
from multiprocessing import Process, Queue
from queue import Empty, Full

import numpy as np
import psutil
import socketio
from new_pipe import daq_fast
from new_pipe.angle import angle_fft
from new_pipe.cfar import cfar_pytorch
from new_pipe.daqv3 import DataAcquisition
from new_pipe.rdm import RangeDoppler

# ================= CONFIG =================
SERVER_URL = "http://127.0.0.1:5001"
RAW_QUEUE_SIZE = 5  # queue between DAQ and processing (smaller = lower latency)
PROCESSED_QUEUE_SIZE = 2  # queue between processing and socket (real-time)
TARGET_FPS = 10  # limit processing loop speed
# =========================================


# -------- Socket.IO --------
def reconnect_socketio():
    sio = socketio.Client()
    try:
        sio.connect(SERVER_URL)
        print("[SOCKET] Connected")
        return sio
    except Exception as e:
        print("[SOCKET] Connect failed:", e)
        return None


# -------- DAQ Process (Core 0) --------
def daq_process(raw_queue):
    """Acquire raw radar data and pass to processing"""
    # Pin to CPU core 0
    psutil.Process(os.getpid()).cpu_affinity([0])
    print("[DAQ] Running on core 0")

    daq = DataAcquisition()
    # daq = daq_fast.DataAcquisition()

    while True:
        t0 = time.perf_counter_ns()
        frame_data = daq.process_v6().copy()
        t1 = time.perf_counter_ns()
        print(f"DAQ: {(t1 - t0) // 1_000}")
        # frame_data = daq.capture_frame()
        # aight this is some actual wizard magic idk
        # 0.02 sleep time is 170ms
        # 0.05 sleep time is 150ms
        # time.sleep(0.01)

        # Non-blocking put - drop current frame if queue full
        try:
            raw_queue.put_nowait(frame_data)
        except Full:
            pass  # Drop frame silently to avoid latency


# -------- RDM/CFAR Processing Process (Core 1) --------
def processing_process(raw_queue, processed_queue):
    """Process raw data through RDM and CFAR"""
    # Pin to CPU core 1
    psutil.Process(os.getpid()).cpu_affinity([1])
    print("[PROCESSING] Running on core 1")

    rdm = RangeDoppler(window="blackman")

    while True:
        t0 = time.perf_counter_ns()
        t0_fps = time.time()

        # Non-blocking get to minimize wait time
        try:
            frame_data = raw_queue.get_nowait()
        except Empty:
            time.sleep(0.001)  # Brief sleep if no data
            continue

        # Process through RDM
        t1 = time.perf_counter_ns()
        rdm.set_buffer(np.array(frame_data, dtype=np.float32))
        frame = rdm.process().reshape(64, 512)
        clean_rdm = rdm.get_clean_rdm()
        t2 = time.perf_counter_ns()

        # Apply CFAR
        cfar_data = cfar_pytorch(
            frame,
            pad_value=np.mean(frame[:, :256]),
            guard_cells_doppler=4,
            guard_cells_range=16,
            training_cells_doppler=6,
            training_cells_range=24,
            threshold_factor=2,
            pad_doppler=18,
            pad_range=50,
            device="cpu",
        )

        t3 = time.perf_counter_ns()

        # Estimate angles for detections
        angle_data = angle_fft(
            cfar_detections=cfar_data,
            clean_rdmap=clean_rdm,
            zero_pad_cols=124,
            device="cpu",
        )
        t4 = time.perf_counter_ns()

        # Package original RDM, CFAR and angle data
        output_data = {"rdm": frame, "cfar": cfar_data, "angles": angle_data}

        # Non-blocking put - drop current frame if queue full
        try:
            processed_queue.put_nowait(output_data)
        except Full:
            pass  # Drop frame to maintain real-time behavior

        t5 = time.perf_counter_ns()

        # FPS limit to avoid CPU overload
        dt = time.time() - t0_fps
        sleep_time = max(0, (1 / TARGET_FPS) - dt)
        # print(
        #     f"DP: {(t5 - t0) // 1_000}, RDM: {(t2 - t1) // 1_000}, CFAR: {(t3 - t2) // 1_000}, ANGLE: {(t4 - t3) // 1_000}"
        # )
        # time.sleep(sleep_time)


# -------- Socket Sender Process (Core 2) --------
def socket_process(processed_queue):
    """Send processed frames via Socket.IO"""
    # Pin to CPU core 2
    # psutil.Process(os.getpid()).cpu_affinity([2])
    print("[SOCKET] Running on core 2")

    sio = None

    while True:
        t0 = time.time()

        # Non-blocking get with brief sleep fallback
        try:
            frame = processed_queue.get_nowait()
        except Empty:
            time.sleep(0.001)
            continue

        if sio is None or not sio.connected:
            sio = reconnect_socketio()
            continue

        try:
            sio.emit(
                "send_frame",
                {
                    "array": frame["rdm"][:, :256].tobytes(),
                    "angles": frame["angles"][:, :256].tolist(),
                    "cfar": frame["cfar"][:, :256].tolist(),
                },
            )
        except Exception as e:
            print("[SOCKET] Send error:", e)
            sio = None
        dt = time.time() - t0
        sleep_time = max(0, (1 / TARGET_FPS) - dt)

        time.sleep(sleep_time)


# -------- MAIN --------
if __name__ == "__main__":
    # Create two queues for the pipeline
    raw_queue = Queue(maxsize=RAW_QUEUE_SIZE)
    processed_queue = Queue(maxsize=PROCESSED_QUEUE_SIZE)

    # Create three processes
    p_daq = Process(target=daq_process, args=(raw_queue,))
    p_processing = Process(target=processing_process, args=(raw_queue, processed_queue))
    p_socket = Process(target=socket_process, args=(processed_queue,))

    # Start all processes
    p_daq.start()
    p_processing.start()
    p_socket.start()

    try:
        p_daq.join()
        p_processing.join()
        p_socket.join()
    except KeyboardInterrupt:
        print("\nExiting...")
        p_daq.terminate()
        p_processing.terminate()
        p_socket.terminate()
