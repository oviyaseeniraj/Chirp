import os
import time
from multiprocessing import Process, Queue
from queue import Empty, Full

import numpy as np
import psutil
import socketio
import math

# from new_pipe import daq_fast
from new_pipe.angle import angle_fft
from new_pipe.cfar import cfar_pytorch
from new_pipe.daqv3 import DataAcquisition
from new_pipe.rdm import RangeDoppler
from dbscan3d import dbscan_cluster_3d
import pytorch as torch

# ================= CONFIG =================
SERVER_URL = "http://127.0.0.1:5001"
RAW_QUEUE_SIZE = 5  # queue between DAQ and processing (smaller = lower latency)
PROCESSED_QUEUE_SIZE = 2  # queue between processing and socket (real-time)
TARGET_FPS = 10  # limit processing loop speed
FRAME_AVG = 100
FRAME_RPL = 20

# 3D Detection map dimensions
RANGE_BINS = 64  # Range dimension (from cfar_data rows)
DOPPLER_BINS = 512  # Doppler dimension (from cfar_data columns)
ANGLE_BINS = 16  # Angle dimension (discretized angle estimates)
# =========================================

# Set the measurement noise parameters for Mahalanobis distance
# Based on Anirban's code - sigma values for [range, doppler, angle]
pi = math.pi
sigma_range = 0.0318
sigma_doppler = 0.1534  # For 64 chirps per frame
sigma_azimuth = pi / 4

# Create 3x3 measurement noise covariance matrix
measurement_noise = np.array([
    [sigma_range**2, 0, 0],
    [0, sigma_doppler**2, 0],
    [0, 0, sigma_azimuth**2]
])


# -------- Socket.IO --------
def reconnect_socketio():
    sio = socketio.Client()
    try:
        sio.connect(SERVER_URL)
        print("[SOCKET] Connected")
        return sio
    except Exception as e:
        # print("[SOCKET] Connect failed:", e)
        return None


# -------- Helper Functions --------
def create_3d_detection_map(cfar_data, angle_data, rdm_power):
    """
    Create a 3D detection map from 2D CFAR detections and angle estimates.
    
    Parameters:
    -----------
    cfar_data : np.ndarray of shape (64, 512)
        2D CFAR detection map (binary: 0 or 1)
    angle_data : np.ndarray of shape (64, 512)
        2D angle estimates in radians
    rdm_power : np.ndarray of shape (64, 512)
        Power values from RDM (actual signal magnitudes)
    
    Returns:
    --------
    detection_coords : np.ndarray of shape (n_detections, 3)
        3D coordinates [range_bin, doppler_bin, angle_bin]
    detection_power : np.ndarray of shape (n_detections,)
        Power values at detection locations
    """
    # Find all detection locations
    detection_mask = cfar_data > 0
    range_indices, doppler_indices = np.where(detection_mask)
    
    if len(range_indices) == 0:
        return np.array([]).reshape(0, 3), np.array([])
    
    # Normalize angle estimates to angle bins [0, ANGLE_BINS-1]
    # Angles typically range from -pi to +pi
    angle_values = angle_data[range_indices, doppler_indices]

    #omega_values = np.pi * np.sin(angle_values)

    angle_bins = np.digitize(angle_values, bins=np.linspace(0, pi, ANGLE_BINS+1)) - 1
    angle_bins = np.clip(angle_bins, 0, ANGLE_BINS - 1)
    
    # Stack into 3D coordinates
    detection_coords = np.column_stack([
        range_indices,
        doppler_indices,
        angle_bins
    ]).astype(np.float32)
    
    # Extract power values from RDM data
    detection_power = rdm_power[range_indices, doppler_indices]
    
    return detection_coords, detection_power

def create_3d_detection_map_spatial(cfar_data, angle_data, rdm_power):
    """
    Create a 3D detection map from 2D CFAR detections and angle estimates.
    
    Parameters:
    -----------
    cfar_data : np.ndarray of shape (64, 512)
        2D CFAR detection map (binary: 0 or 1)
    angle_data : np.ndarray of shape (64, 512)
        2D angle estimates in radians
    rdm_power : np.ndarray of shape (64, 512)
        Power values from RDM (actual signal magnitudes)
    
    Returns:
    --------
    detection_coords : np.ndarray of shape (n_detections, 3)
        3D coordinates [range_bin, doppler_bin, spatial_freq_bin]
    detection_power : np.ndarray of shape (n_detections,)
        Power values at detection locations
    """
    # Find all detection locations
    detection_mask = cfar_data > 0
    range_indices, doppler_indices = np.where(detection_mask)
    
    if len(range_indices) == 0:
        return np.array([]).reshape(0, 3), np.array([])
    
    # Extract angle values at detection locations
    angle_values = angle_data[range_indices, doppler_indices]
    
    # Convert angles to spatial frequency: omega = pi * sin(angle)
    spatial_freq_values = np.pi * np.sin(angle_values)
    
    # Normalize spatial frequency to bins [0, ANGLE_BINS-1]
    # Spatial frequency ranges from -pi to +pi
    spatial_freq_bins = np.digitize(spatial_freq_values, bins=np.linspace(-np.pi, np.pi, ANGLE_BINS + 1)) - 1
    spatial_freq_bins = np.clip(spatial_freq_bins, 0, ANGLE_BINS)
    
    # Stack into 3D coordinates
    detection_coords = np.column_stack([
        range_indices,
        doppler_indices,
        spatial_freq_bins
    ]).astype(np.float32)
    
    # Extract power values from RDM data
    detection_power = rdm_power[range_indices, doppler_indices]
    
    return detection_coords, detection_power    

def extract_clusters_from_3d(detection_coords_3d, cluster_labels):
    """
    Convert 3D cluster labels back to 2D cluster map.
    
    Parameters:
    -----------
    detection_coords : np.ndarray of shape (n_detections, 3)
        3D coordinates of detections
    cluster_labels : np.ndarray of shape (n_detections,)
        Cluster labels from DBSCAN 3D
    detection_power : np.ndarray of shape (n_detections,)
        Power values at each detection
    cfar_data_shape : tuple
        Shape of original CFAR data (64, 512)
    
    Returns:
    --------
    cluster_map : np.ndarray of shape cfar_data_shape
        2D cluster map with cluster IDs at detection locations
    """
    shape3d= detection_coords_3d.shape
    data_shape_2d = [shape3d[0], shape3d[1]]
    cluster_map = np.zeros(data_shape_2d, dtype=np.int32)
    
    # Map back to 2D coordinates
    for i, (coord, label) in enumerate(zip(detection_coords_3d, cluster_labels)):
        range_idx = int(coord[0])
        doppler_idx = int(coord[1])
        
        # Ensure indices are within bounds
        if 0 <= range_idx < data_shape_2d[0] and 0 <= doppler_idx < data_shape_2d[1]:
            cluster_map[range_idx, doppler_idx] = label
    
    return cluster_map


# -------- DAQ Process (Core 0) --------
def daq_process(raw_queue):
    """Acquire raw radar data and pass to processing"""
    # Pin to CPU core 0
    psutil.Process(os.getpid()).cpu_affinity([0])
    print("[DAQ] Running on core 0")

    daq = DataAcquisition()
    # daq = daq_fast.DataAcquisition()

    # FPS tracking
    last_frame_time = None
    frame_times = []
    frame_count = 0

    while True:
        t0 = time.perf_counter_ns()
        frame_data = daq.process_v6().copy()
        t1 = time.perf_counter_ns()

        # Track frame arrival time for FPS calculation
        current_time = time.time()
        if last_frame_time is not None:
            frame_interval = current_time - last_frame_time
            frame_times.append(frame_interval)

            # Keep last 30 frame intervals for rolling average
            if len(frame_times) > FRAME_AVG:
                frame_times.pop(0)

            # Print FPS every 10 frames
            frame_count += 1
            if frame_count % FRAME_RPL == 0:
                avg_interval = sum(frame_times) / len(frame_times)
                fps = 1.0 / avg_interval if avg_interval > 0 else 0

                # Calculate variance and standard deviation
                variance = sum((t - avg_interval) ** 2 for t in frame_times) / len(
                    frame_times
                )
                std_dev = variance**0.5

                print(
                    f"[DAQ] FPS: {fps:.2f} | Avg interval: {avg_interval * 1000:.1f}ms | "
                    f"Std dev: {std_dev * 1000:.2f}ms | Variance: {variance * 1000000:.2f}ms² | "
                    f"Last: {frame_interval * 1000:.1f}ms"
                )

        last_frame_time = current_time

        # Non-blocking put - drop current frame if queue full
        try:
            raw_queue.put_nowait(frame_data)
        except Full:
            pass  # Drop frame silently to avoid latency


# -------- RDM/CFAR/3D Detection Processing Process (Core 1) --------
def processing_process(raw_queue, processed_queue):
    """Process raw data through RDM, CFAR, angle estimation, and 3D DBSCAN"""
    # Pin to CPU core 1
    psutil.Process(os.getpid()).cpu_affinity([1])
    print("[PROCESSING] Running on core 1")

    rdm = RangeDoppler(window="blackman", alpha=0.1)

    # FPS tracking
    last_frame_time = None
    frame_times = []
    frame_count = 0

    while True:
        t0 = time.perf_counter_ns()
        t0_fps = time.time()

        # Non-blocking get to minimize wait time
        try:
            frame_data = raw_queue.get_nowait()
        except Empty:
            time.sleep(0.001)  # Brief sleep if no data
            continue

        # Track frame processing time for FPS calculation
        current_time = time.time()
        if last_frame_time is not None:
            frame_interval = current_time - last_frame_time
            frame_times.append(frame_interval)

            # Keep last 30 frame intervals for rolling average
            if len(frame_times) > FRAME_AVG:
                frame_times.pop(0)

        last_frame_time = current_time

        # Process through RDM
        t1 = time.perf_counter_ns()
        rdm.set_buffer(np.array(frame_data, dtype=np.float32))
        frame = rdm.process().reshape(64, 512)
        clean_rdm = rdm.get_clean_rdm()
        t2 = time.perf_counter_ns()

        # Apply CFAR
        cfar_data = cfar_pytorch(
            frame,
            pad_value=np.mean(frame[:, :512]),
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

        #phase_data = pi * np.sin(angle_data)

        t4 = time.perf_counter_ns()

        # ========== 3D DETECTION MAPPING ==========
        # Create 3D detection coordinates from 2D CFAR + angle data
        detection_coords, detection_power = create_3d_detection_map_spatial(cfar_data, angle_data,frame)
        
        t4b = time.perf_counter_ns()

        # ========== 3D DBSCAN CLUSTERING ==========
        if len(detection_coords) > 0:
            print(len(detection_coords))
            # Perform 3D DBSCAN clustering with Mahalanobis distance
            cluster_labels_3d, n_clusters, centroids = dbscan_cluster_3d(
                detection_coords,
                eps=5.0,  # Tune based on your 3D space
                min_samples=3,
                metric="mahalanobis",
                scale_coords=True,
                x_weight=1.0,  # Range weight (512)
                y_weight=0.25,  # Doppler weight (64 dimension)
                z_weight=0.15,  # Angle weight (64 smaller dimension)
                measurement_noise_matrix=measurement_noise,
                device="cpu",
            )
            #print(n_clusters)
            #print(centroids)
            # Convert 3D cluster labels back to 2D map (discard angle)
            dbscan_data_2d = extract_clusters_from_3d(detection_coords, cluster_labels_3d)


            centroids_2d = { cluster_id: torch.floor(centroid[:2]).int() for cluster_id, centroid in centroids.items()}
            print(centroids_2d)

            centroid_map = np.zeros(cfar_data.shape)
            
            centroids_2d = extract_clusters_from_3d()


        else:
            dbscan_data_2d = np.zeros_like(cfar_data, dtype=np.int32)

        t5 = time.perf_counter_ns()


        # Package original RDM, CFAR, angle and 3D DBSCAN data
        output_data = {
            "rdm": dbscan_data_2d,
            "cfar": cfar_data,
            "angles": angle_data,
            "dbscan_data_2d": dbscan_data_2d,
            "detection_coords": detection_coords,
            "cluster_labels": cluster_labels_3d if len(detection_coords) > 0 else np.array([])
        }

        # Non-blocking put - drop current frame if queue full
        try:
            processed_queue.put_nowait(output_data)
        except Full:
            pass  # Drop frame to maintain real-time behavior

        t6 = time.perf_counter_ns()

        # Print timing every 10 frames with FPS
        frame_count += 1
        if frame_count % FRAME_RPL == 0 and len(frame_times) > 0:
            avg_interval = sum(frame_times) / len(frame_times)
            fps = 1.0 / avg_interval if avg_interval > 0 else 0
            print(
                f"[PROCESSING] FPS: {fps:.2f} | Avg interval: {avg_interval * 1000:.1f}ms | "
                f"Total: {(t5 - t0) // 1_000}us, RDM: {(t2 - t1) // 1_000}us, CFAR: {(t3 - t2) // 1_000}us, "
                f"ANGLE: {(t4 - t3) // 1_000}us, 3D_MAP: {(t4b - t4) // 1_000}us, DBSCAN3D: {(t5 - t4b) // 1_000}us"
            )
            print(f"CFAR Detections: {np.sum(cfar_data > 0)} | 3D Clusters: {np.max(dbscan_data_2d)}")


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
                    "array": frame["rdm"][:, :512].tobytes(),
                    "angles": frame["angles"][:, :512].tobytes(),
                    "cfar": frame["cfar"][:, :512].tobytes(),
                    "dbscan_data_2d": frame["dbscan_data_2d"][:, :512].tobytes(),
                },
            )
        except Exception as e:
            print("[SOCKET] Send error:", e)
            sio = None


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