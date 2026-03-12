from filterpy.kalman import ExtendedKalmanFilter
from filterpy.common import Q_discrete_white_noise
import math
import os
import time
from multiprocessing import Process, Queue
from queue import Empty, Full

from datetime import datetime, timedelta
import numpy as np
import psutil
import socketio
import torch
from dbscan3d import dbscan_process, centroids_visualize

# from new_pipe import daq_fast
from new_pipe.angle import angle_fft
from collections import defaultdict
import threading

from new_pipe.stone_soup_ekf_anirban import StoneSoupJPDATracker

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
                # Use mean range and angle
                mean_range = np.mean(dets[:,0])
                mean_angle = np.mean(dets[:,2])
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


from new_pipe.cfar import cfar_pytorch
from new_pipe.daqv3 import DataAcquisition
from new_pipe.rdm import RangeDoppler

# ================= CONFIG =================
SERVER_URL = "http://169.231.93.105:5001"
RAW_QUEUE_SIZE = 5  # queue between DAQ and processing (smaller = lower latency)
PROCESSED_QUEUE_SIZE = 2  # queue between processing and socket (real-time)
TARGET_FPS = 10  # limit processing loop speed
FRAME_AVG = 100
FRAME_RPL = 20

# 3D Detection map dimensions
RANGE_BINS = 512  # Range dimension (from cfar_data rows)
DOPPLER_BINS = 64  # Doppler dimension (from cfar_data columns)
ANGLE_BINS = 16  # Angle dimension (discretized angle estimates)

MIN_CLUSTER_SIZE = 5
LOW_PASS_FILTER_DECAY = 0.8
# =========================================

# ================= CONFIG =================

# Radar Physical Constants (Adjust these to match your hardware config)
FS = 10e6                 # Sampling frequency (Hz)
SLOPE = 70e12             # Frequency slope (Hz/s)
C = 3e8                   # Speed of light (m/s)
FC = 60.25e9              # Center frequency (Hz)
IDLE_TIME = 100e-6        # Idle time (s)
RAMP_END_TIME = 60e-6     # Ramp end time (s)
NUM_ADC_SAMPLES = 512      # Range bins
NUM_CHIRPS = 64          # Doppler bins
T_CHIRP = IDLE_TIME + RAMP_END_TIME

# Derived Resolutions
#RANGE_RES = (C * FS) / (2 * SLOPE * NUM_ADC_SAMPLES)
RANGE_RES = 0.035
# Velocity resolution: lambda / (2 * Total_Frame_Time)
#LAMBDA = C / FC
#VEL_RES = LAMBDA / (2 * NUM_CHIRPS * T_CHIRP)
VEL_RES = 0.2
# =========================================
...


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

    # omega_values = np.pi * np.sin(angle_values)

    angle_bins = np.digitize(angle_values, bins=np.linspace(0, pi, ANGLE_BINS + 1)) - 1
    angle_bins = np.clip(angle_bins, 0, ANGLE_BINS - 1)

    # Stack into 3D coordinates
    detection_coords = np.column_stack(
        [range_indices, doppler_indices, angle_bins]
    ).astype(np.float32)

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

    # Normalize spatial frequency to bins [0, ANGLE_BINS-1]
    # Spatial frequency ranges from -pi to +pi
    # Stack into 3D coordinates

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

    #assume sampling at 15 HZ
    jpda = StoneSoupJPDATracker(
    dt=0.1,                          # 10Hz sampling
    detection_probability=0.9,       # MATLAB Pd
    clutter_density=0.05,            # Raised for multi-target (reduces over-claiming)
    gate_probability=0.99,           # Gating
    sigma_a=0.1,                     # Process noise
    sigma_range=RANGE_RES,                 # Range noise
    sigma_doppler=VEL_RES,               # Velocity noise
    sigma_angle=np.pi/4.0            # Angle noise
    )

    # FPS tracking
    last_frame_time = None
    frame_times = []
    frame_count = 0

    m_cfar_data = np.zeros((RANGE_BINS, DOPPLER_BINS), dtype=np.float32)
    m_dbscan_data = np.zeros((RANGE_BINS, DOPPLER_BINS), dtype=np.float32)
    m_angle_data = np.zeros((RANGE_BINS, DOPPLER_BINS), dtype=np.float32)
    m_cluster_data = np.zeros((RANGE_BINS, DOPPLER_BINS), dtype=np.float32)

    import pickle
    node_id = os.getenv('NODE_ID', 'node1')
    calibration_save_file = f"calibration_data_{node_id}.pkl"
    calibration_data_dict = {}
    save_interval = 10  # Save every N frames
    frame_num = 0
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
        frame_num += 1

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

        # cfar_data[32,:]= 0

        # Estimate angles for detections
        angle_data = angle_fft(
            cfar_detections=cfar_data,
            clean_rdmap=clean_rdm,
            zero_pad_cols=124,
            device="cpu",
        )
        # phase_data = pi * np.sin(angle_data)

        t4 = time.perf_counter_ns()

        # ========== 3D DETECTION MAPPING ==========
        # Create 3D detection coordinates from 2D CFAR + angle data
        detection_coords_3d, detection_power = create_3d_detection_map_spatial(
            cfar_data, angle_data, frame
        )

        t4b = time.perf_counter_ns()

        dbscan_data_2d, dbscan_angles, centroids = dbscan_process(detection_coords_3d, cfar_data.shape)

        # Apply EKF to centroids immediately after extraction
        # centroids_ekf output: [x, y, vx, vy] in Cartesian coordinates
        #centroids_ekf = apply_ekf_to_centroids(centroids, node_id=node_id)
        t4c = time.perf_counter_ns()

        # For visualization, continue using original centroids mapped to 2D
        centroids_map, centroids_angles = centroids_visualize(centroids, cfar_data.shape)

        t4d = time.perf_counter_ns() 

        #convert to estimate of actual velocities and ranges, rather than bins
        #zero bin removal for centroids
        eps = 0.2
        rda_centroids = {}
        for label,data in centroids.items():
            state = data[0]
            vel_bin, range_bin = state[0], state[1]

            #get rid of reflections
            #if (range_bin > 256):
            #    continue

            angle = state[2]
            num_points = data[1]

            vel_val = (vel_bin - 32) * VEL_RES
            range_val = range_bin * RANGE_RES

            if abs(vel_bin - 32) > eps: #keep moving targets
                rda_centroids[label] = (torch.tensor([range_val, vel_val, angle]), num_points)
            else:
                pass
                #print("filtrum")

        #if len(rda_centroids) > 0:
        #    items = rda_centroids.items()
        #    print(items)
        #print(len(rda_centroids))

        current_timestamp = datetime.now()
        confirmed_tracks, tentative_tracks = jpda.process_frame(rda_centroids, current_timestamp)

        # Create visualization maps for confirmed tracks
        confirmed_tracks_map = np.zeros_like(frame, dtype=np.float32)
        confirmed_tracks_angles = np.zeros_like(frame, dtype=np.float32)

        print(f"Confirmed: {len(confirmed_tracks)} | Tentative: {len(tentative_tracks)}")
        for track in confirmed_tracks:
            tid = track['TrackID']
            state = track['State'] # [x, y, vx, vy]
            misses = track['ConsecutiveMisses']
            detection = track['Detection'] # [range (m), velocity (m/s), angle (rad)]
            
            # --- Convert physical units back to RDM bins ---
            range_val, vel_val, angle_rad = detection
            
            # 1. Convert range (m) to range bin
            range_bin = int(round(range_val / RANGE_RES))
            range_bin = np.clip(range_bin, 0, RANGE_BINS-1)
            
            # 2. Convert velocity (m/s) to Doppler bin
            # The zero-velocity bin is at DOPPLER_BINS / 2 = 32
            doppler_bin = int(round((vel_val / VEL_RES) + (DOPPLER_BINS / 2)))
            doppler_bin = np.clip(doppler_bin, 0, DOPPLER_BINS-1)

            # 3. Populate the visualization maps
            if 0 <= range_bin < RANGE_BINS and 0 <= doppler_bin < DOPPLER_BINS:
                confirmed_tracks_map[doppler_bin, range_bin] = 1.0  # Mark the spot
                confirmed_tracks_angles[doppler_bin, range_bin] = np.rad2deg(angle_rad)

            print(f"Track {tid} at x={state[0]:.2f}, y={state[1]:.2f}, misses={misses}, avg det={detection}")

        # You can now send these maps to the socket process
        
        #tentative_tracks = []
        #confirmed_tracks = []
        #print("tentative dist",jpda.average_tentative_mahalanobis_distance())

        #print(len(centroids))
        #print(confirmed_tracks)
        #print("confirmed dist", jpda.compute_pairwise_mahalanobis_distances(confirmed_tracks,True))

        #confirmed_centroids = {track['TrackID']: for i in }
        #print("cent:",len(centroids), np.sum(centroids_map))
        #confirmed_tracks = []
        #print(len(tentative_tracks))
        #print([t['State'] for t in tentative_tracks])
        #print(len(confirmed_tracks))

        #print(dbscan_data_2d)
        t5 = time.perf_counter_ns()

        # low_pass filter everthing across time
        # m_cfar_data = (m_cfar_data * LOW_PASS_FILTER_DECAY + cfar_data)
        # m_dbscan_data = m_dbscan_data * LOW_PASS_FILTER_DECAY + dbscan_data_2d.astype(np.float32) * (1-LOW_PASS_FILTER_DECAY)

        # m_angle_data = m_angle_data * LOW_PASS_FILTER_DECAY + angle_data * (1-LOW_PASS_FILTER_DECAY)
        # m_centroids_map = m_cluster_data * LOW_PASS_FILTER_DECAY + centroids_map
        #m_angle_data[np.where(m_angle_data > 5 * np.max(m_angle_data) / 6)] = 0

        np.set_printoptions(threshold=np.inf)
        # print(np.sum(m_cfar_data.astype(int)))
        # print("max",np.max(m_angle_data))
        # print("median",np.median(m_angle_data))
        # print("variance",np.variance(m_cfar_data))
        # print("90th percentile",np.percentile(m_angle_data,50))

        # print(type(m_angle_data))
        # print(type(angle_data))

        # print(m_dbscan_data.dtype)

        # print(m_angle_data.astype(int).shape)
        # print(angle_data.shape)
        # print(m_angle_data.dtype)
        # print(angle_data.dtype)

        output_data = {
            "rdm": frame,
            "cfar": cfar_data,
            "angles": angle_data,
            "dbscan_data_2d": dbscan_data_2d,
            "detection_coords": detection_coords_3d if len(detection_coords_3d) > 0 else np.array([]),
            "centroids_ekf": confirmed_tracks if confirmed_tracks is not None and len(confirmed_tracks) > 0 else np.array([]),
            "node_id": node_id,
            "frame_num": frame_num,
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
                f"ANGLE: {(t4 - t3) // 1_000}us, 3D_MAP: {(t4b - t4) // 1_000}us, DBSCAN3D: {(t4c - t4b) // 1_000}us, CENTROID: {(t4d - t4c) // 1_000}us, JPDA/EKF: {(t5 - t4d) // 1_000}us"
            )
            print(
                f"CFAR Detections: {np.sum(cfar_data > 0)} | 3D Clusters: {np.max(dbscan_data_2d)}"
            )


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
                    # Send EKF-filtered centroids to spatial_calibration
                    #"centroids_ekf": frame["centroids_ekf"].tobytes() if frame["centroids_ekf"].size > 0 else b'',
                    "node_id": frame["node_id"],
                    "frame_num": frame["frame_num"],
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
