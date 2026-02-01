import os
import time
from multiprocessing import Process, Queue

import numpy as np
import psutil
import socketio

# from _typeshed import ExcInfo
from new_pipe.cfar import cfar_pytorch
from new_pipe.daqv2 import DataAcquisition
from new_pipe.rdm import RangeDoppler

# ================= CONFIG =================
SERVER_URL = "http://127.0.0.1:5000"
RAW_QUEUE_SIZE = 10  # queue between DAQ and processing
PROCESSED_QUEUE_SIZE = 10  # queue between processing and socket (real-time)
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

    while True:
        frame_data = daq.process()
        # aight this is some actual wizard magic idk
        # 0.02 sleep time is 170ms
        # 0.05 sleep time is 150ms
        time.sleep(0.05)

        # Drop old frame if queue full (keep pipeline flowing)
        if raw_queue.full():
            print("drop")
            raw_queue.get()

        raw_queue.put(frame_data)


# -------- RDM/CFAR Processing Process (Core 1) --------
def processing_process(raw_queue, processed_queue):
    """Process raw data through RDM and CFAR"""
    # Pin to CPU core 1
    psutil.Process(os.getpid()).cpu_affinity([1])
    print("[PROCESSING] Running on core 1")

    rdm = RangeDoppler(window="blackman")

    while True:
        t0 = time.time()

        frame_data = raw_queue.get()

        # Process through RDM
        rdm.set_buffer(np.array(frame_data, dtype=np.float32))
        frame = rdm.process().reshape(64, 512)
        # Apply CFAR
        cfar_data = cfar_pytorch(
            frame,
            pad_value=np.mean(frame[:, :256]),
            guard_cells_doppler=4,
            guard_cells_range=16,
            training_cells_doppler=6,
            training_cells_range=24,
            threshold_factor=2.5,
            pad_doppler=32,
            pad_range=128,
            device="cpu",
        )

        # Drop old frame if queue full (real-time behavior)
        if processed_queue.full():
            processed_queue.get()

        processed_queue.put(frame[:, :256])

        # FPS limit to avoid CPU overload
        dt = time.time() - t0
        sleep_time = max(0, (1 / TARGET_FPS) - dt)
        # print(f"dt: {dt:.6f}, sleep_time: {sleep_time:.6f}")

        time.sleep(sleep_time)


# -------- Socket Sender Process (Core 2) --------
def socket_process(processed_queue):
    """Send processed frames via Socket.IO"""
    # Pin to CPU core 2
    # psutil.Process(os.getpid()).cpu_affinity([2])
    print("[SOCKET] Running on core 2")

    sio = None

    while True:
        t0 = time.time()
        # Blocking wait = zero CPU spin

        frame = processed_queue.get()

        if sio is None or not sio.connected:
            sio = reconnect_socketio()
            continue

        try:
            sio.emit(
                "send_frame",
                {
                    "array": frame[:, :256].tobytes(),
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
