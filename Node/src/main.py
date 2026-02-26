import math
import os
import time
import signal
import sys
import socket
import pickle
import threading
from multiprocessing import Process, Queue
from queue import Empty, Full
from collections import defaultdict

import numpy as np
import psutil
import socketio
import torch

# Local imports
from .radar import config
from .radar.daq import DataAcquisition
from .radar.processing.angle import angle_fft
from .radar.processing.cfar import cfar_pytorch
from .radar.processing.rdm import RangeDoppler
from .radar.processing.clustering import dbscan_process, centroid_process

# ================= CONFIG =================
SERVER_URL = os.getenv("SERVER_URL", "http://127.0.0.1:5001")
NODE_ID = os.getenv("NODE_ID", socket.gethostname())
RAW_QUEUE_SIZE = 5  # queue between DAQ and processing
PROCESSED_QUEUE_SIZE = 2  # queue between processing and socket
FRAME_AVG = 100
FRAME_RPL = 20

# 3D Detection map dimensions (from config if possible)
RANGE_BINS = config.FAST_TIME
DOPPLER_BINS = config.SLOW_TIME
# Note: ANGLE_BINS is used in create_3d_detection_map but not in spatial version
LOW_PASS_FILTER_DECAY = 0.8
# =========================================


# -------- Calibration Manager --------
class CalibrationManager:
    def __init__(self, num_nodes=4, calibration_window=50):
        self.num_nodes = num_nodes
        self.calibration_window = calibration_window
        self.node_data = defaultdict(lambda: defaultdict(list))  # node_id -> frame_num -> detections
        self.lock = threading.Lock()

    def add_detection(self, node_id, frame_num, detection_coords):
        with self.lock:
            self.node_data[node_id][frame_num].append(detection_coords)

    def check_ready(self):
        with self.lock:
            # Find frames present in all nodes
            frame_sets = [set(frames.keys()) for frames in self.node_data.values()]
            if len(frame_sets) < self.num_nodes:
                return None
            common_frames = set.intersection(*frame_sets)
            # Only calibrate if enough frames
            if len(common_frames) >= self.calibration_window:
                return sorted(list(common_frames))[-self.calibration_window:]
            return None

    def get_calibration_data(self, frames):
        with self.lock:
            # Returns: node_id -> [detections for each frame]
            calibration_data = {}
            for node_id in self.node_data:
                calibration_data[node_id] = []
                for frame_num in frames:
                    # Flatten detections for this frame
                    detections = self.node_data[node_id][frame_num]
                    if detections:
                        calibration_data[node_id].append(np.concatenate(detections, axis=0))
                    else:
                        calibration_data[node_id].append(np.array([]))
            return calibration_data

    def clear_calibration_frames(self, frames):
        with self.lock:
            for node_id in self.node_data:
                for frame_num in frames:
                    if frame_num in self.node_data[node_id]:
                        del self.node_data[node_id][frame_num]


# -------- Closed-Form Calibration --------
def closed_form_calibration(calibration_data):
    """
    calibration_data: dict of node_id -> [trajectory (complex) for each frame]
    Returns: position and orientation matrices
    """
    node_ids = list(calibration_data.keys())
    num_nodes = len(node_ids)
    num_frames = len(calibration_data[node_ids[0]])
    # Build trajectory matrix: shape (num_nodes, num_frames)
    trajectory = np.zeros((num_nodes, num_frames), dtype=np.complex64)
    for i, node_id in enumerate(node_ids):
        for t in range(num_frames):
            # Use centroid of detections for each frame
            dets = calibration_data[node_id][t]
            if dets.size == 0:
                trajectory[i, t] = np.nan
            else:
                # Convert range, angle to complex position
                # dets shape: (n, 3) [range_bin, doppler_bin, angle]
                mean_range = np.mean(dets[:, 0])
                mean_angle = np.mean(dets[:, 2])
                trajectory[i, t] = mean_range * np.exp(1j * mean_angle)

    # Remove frames with NaN
    valid_mask = ~np.isnan(trajectory).any(axis=0)
    trajectory = trajectory[:, valid_mask]
    num_frames = trajectory.shape[1]
    if num_frames == 0:
        return None, None

    # Closed-form calibration
    P_opt = np.zeros((num_nodes, num_nodes), dtype=np.complex64)
    theta_opt = np.zeros((num_nodes, num_nodes))
    for i in range(num_nodes):
        for k in range(num_nodes):
            z_i = trajectory[i, :]
            z_k = trajectory[k, :]
            z_i_mean = np.mean(z_i)
            z_k_mean = np.mean(z_k)
            val = np.sum((z_k - z_k_mean) * np.conj(z_i - z_i_mean))
            phi = np.arctan2(val.imag, val.real)
            theta_opt[i, k] = np.rad2deg(-phi)
            P_opt[i, k] = z_i_mean - np.exp(-1j * phi) * z_k_mean
    return P_opt, theta_opt


# -------- Helper Functions --------
def create_3d_detection_map_spatial(cfar_data, angle_data, rdm_power):
    """
    Create a 3D detection map from 2D CFAR detections and angle estimates.
    Returns [range_bin, doppler_bin, angle]
    """
    # Find all detection locations
    detection_mask = cfar_data > 0
    range_indices, doppler_indices = np.where(detection_mask)

    if len(range_indices) == 0:
        return np.array([]).reshape(0, 3), np.array([])

    # Extract angle values at detection locations
    angle_values = angle_data[range_indices, doppler_indices]

    detection_coords = np.column_stack(
        [range_indices, doppler_indices, angle_values]
    ).astype(np.float32)

    # Extract power values from RDM data
    detection_power = rdm_power[range_indices, doppler_indices]

    return detection_coords, detection_power


# -------- DAQ Process (Core 0) --------
def daq_process(raw_queue):
    """Acquire raw radar data and pass to processing"""
    # Pin to CPU core 0
    try:
        psutil.Process(os.getpid()).cpu_affinity([0])
    except Exception as e:
        print(f"[DAQ] Affinitiy failed: {e}")
    
    print("[DAQ] Running on core 0")

    with DataAcquisition() as daq:
        # FPS tracking
        last_frame_time = None
        frame_times = []
        frame_count = 0

        while True:
            try:
                frame_data = daq.capture()
                
                # Track frame arrival time for FPS calculation
                current_time = time.time()
                if last_frame_time is not None:
                    frame_interval = current_time - last_frame_time
                    frame_times.append(frame_interval)

                    if len(frame_times) > FRAME_AVG:
                        frame_times.pop(0)

                    frame_count += 1
                    if frame_count % FRAME_RPL == 0:
                        avg_interval = sum(frame_times) / len(frame_times)
                        fps = 1.0 / avg_interval if avg_interval > 0 else 0
                        variance = sum((t - avg_interval) ** 2 for t in frame_times) / len(frame_times)
                        std_dev = variance**0.5
                        print(
                            f"[DAQ] FPS: {fps:.2f} | Avg: {avg_interval * 1000:.1f}ms | Std: {std_dev * 1000:.2f}ms"
                        )

                last_frame_time = current_time

                # Non-blocking put - drop current frame if queue full
                try:
                    raw_queue.put_nowait(frame_data.copy())
                except Full:
                    pass
            except Exception as e:
                print(f"[DAQ] Error: {e}")
                time.sleep(0.1)


# -------- Processing Process (Core 1) --------
def processing_process(raw_queue, processed_queue):
    """Process raw data through RDM, CFAR, angle estimation, and 3D DBSCAN"""
    # Pin to CPU core 1
    try:
        psutil.Process(os.getpid()).cpu_affinity([1])
    except Exception as e:
        print(f"[PROCESSING] Affinity failed: {e}")
        
    print("[PROCESSING] Running on core 1")

    rdm = RangeDoppler(window="blackman", alpha=0.1)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[PROCESSING] Using device: {device}")

    # FPS tracking
    last_frame_time = None
    frame_times = []
    frame_count = 0

    calibration_save_file = f"calibration_data_{NODE_ID}.pkl"
    calibration_data_dict = {}
    save_interval = 10
    frame_num = 0

    while True:
        try:
            # Get raw data
            try:
                frame_data = raw_queue.get(timeout=1.0)
            except Empty:
                continue

            t0 = time.perf_counter_ns()

            # 1. Range-Doppler Processing
            rdm.set_buffer(frame_data)
            rdm_mag = rdm.process().reshape(config.SLOW_TIME, config.FAST_TIME)
            clean_rdm = rdm.get_clean_rdm()
            t1 = time.perf_counter_ns()
            frame_num += 1

            # 2. CFAR Detection
            cfar_data = cfar_pytorch(
                rdm_mag,
                guard_cells_doppler=4,
                guard_cells_range=16,
                training_cells_doppler=6,
                training_cells_range=24,
                threshold_factor=2,
                pad_doppler=18,
                pad_range=50,
                device=device,
            )
            t2 = time.perf_counter_ns()

            # 3. Angle Estimation
            angle_data = angle_fft(
                cfar_detections=cfar_data,
                clean_rdmap=clean_rdm,
                zero_pad_cols=124,
                device=device,
            )
            t3 = time.perf_counter_ns()

            # 4. 3D Detection Mapping
            detection_coords_3d, detection_power = create_3d_detection_map_spatial(
                cfar_data, angle_data, rdm_mag
            )
            t4 = time.perf_counter_ns()

            # 5. 3D DBSCAN and Centroids
            dbscan_data_2d, dbscan_angles, centroids = dbscan_process(detection_coords_3d, cfar_data.shape)
            t5 = time.perf_counter_ns()

            # 6. Centroid Processing
            centroids_map, centroids_angles = centroid_process(centroids, cfar_data.shape)
            t6 = time.perf_counter_ns()

            # Calibration Hook
            if centroids and len(centroids) > 0:
                # Store (range_bin, doppler_bin, angle) for each centroid
                # centroid_data format depends on clustering.py Implementation
                # In clustering.py, self.cluster_centroids_[id] = (tensor([x, y, angle]), size)
                centroid_values = [v[0].cpu().numpy() for v in centroids.values()]
                calibration_data_dict[frame_num] = np.array(centroid_values)

            if frame_num % save_interval == 0 and calibration_data_dict:
                try:
                    with open(calibration_save_file, 'wb') as f:
                        pickle.dump(calibration_data_dict, f)
                except Exception as e:
                    print(f"[PROCESSING] Save failed: {e}")

            # Pack output
            output_data = {
                "node_id": NODE_ID,
                "timestamp": int(time.time() * 1000),
                "centroids": detection_coords_3d.astype(np.float32).tobytes() if len(detection_coords_3d) > 0 else b"",
                "image_data": rdm_mag.astype(np.float32).tobytes(),
                "angles": angle_data.astype(np.float32).tobytes() if angle_data is not None else b"",
                "cfar": cfar_data.astype(np.float32).tobytes() if cfar_data is not None else b""
            }

            try:
                processed_queue.put_nowait(output_data)
            except Full:
                pass

            # Timing and FPS
            t_end = time.perf_counter_ns()
            current_time = time.time()
            if last_frame_time is not None:
                frame_times.append(current_time - last_frame_time)
                if len(frame_times) > FRAME_AVG:
                    frame_times.pop(0)
                
                frame_count += 1
                if frame_count % FRAME_RPL == 0:
                    fps = 1.0 / (sum(frame_times) / len(frame_times))
                    print(
                        f"[PROCESSING] FPS: {fps:.2f} | Total: {(t_end - t0) // 1_000_000}ms | "
                        f"RDM: {(t1 - t0) // 1_000_000}ms, CFAR: {(t2 - t1) // 1_000_000}ms, "
                        f"Angle: {(t3 - t2) // 1_000_000}ms, DBSCAN: {(t5 - t4) // 1_000_000}ms"
                    )

            last_frame_time = current_time

        except Exception as e:
            print(f"[PROCESSING] Error: {e}")
            import traceback
            traceback.print_exc()


# -------- Socket Sender Process (Core 2) --------
def socket_process(processed_queue):
    """Send processed frames via Socket.IO"""
    print("[SOCKET] Started")
    sio = socketio.Client()
    connected = False

    while True:
        try:
            if not connected:
                try:
                    sio.connect(SERVER_URL)
                    print(f"[SOCKET] Connected to {SERVER_URL}")
                    connected = True
                except Exception:
                    time.sleep(1)
                    continue

            try:
                frame = processed_queue.get(timeout=1.0)
            except Empty:
                continue

            try:
                # Send data expected by fast_plotter_3 / ui server
                sio.emit("send_frame", {
                    "node_id": frame["node_id"],
                    "frame_num": frame["timestamp"],
                    "centroids": frame["centroids"],
                    "array": frame.get("image_data", b""),
                    "angles": frame.get("angles", b""),
                    "cfar": frame.get("cfar", b"")
                })
            except Exception as e:
                print(f"[SOCKET] Send error: {e}")
                connected = False

        except Exception as e:
            print(f"[SOCKET] Loop error: {e}")
            connected = False
            time.sleep(1)


def main():
    # Signal handling
    def signal_handler(sig, frame):
        print("\nShutting down...")
        p_daq.terminate()
        p_proc.terminate()
        p_sock.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Create queues
    raw_queue = Queue(maxsize=RAW_QUEUE_SIZE)
    processed_queue = Queue(maxsize=PROCESSED_QUEUE_SIZE)

    # Create processes
    p_daq = Process(target=daq_process, args=(raw_queue,), name="DAQ")
    p_proc = Process(target=processing_process, args=(raw_queue, processed_queue), name="Processing")
    p_sock = Process(target=socket_process, args=(processed_queue,), name="Socket")

    # Start processes
    p_daq.start()
    p_proc.start()
    p_sock.start()

    print(f"Node {NODE_ID} started. Connecting to {SERVER_URL}")

    p_daq.join()
    p_proc.join()
    p_sock.join()


if __name__ == "__main__":
    main()
