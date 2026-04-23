import threading
import numpy as np
from collections import defaultdict

class CalibrationManager:
    """
    Manages multi-node calibration data, collecting detections across nodes
    to find common frames for spatial calibration.
    """
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

def closed_form_calibration(calibration_data):
    """
    Performs closed-form spatial calibration across multiple nodes.
    
    Parameters:
    -----------
    calibration_data: dict of node_id -> [trajectory (complex) for each frame]
    
    Returns:
    --------
    P_opt: position translation matrix
    theta_opt: orientation rotation matrix
    """
    node_ids = list(calibration_data.keys())
    num_nodes = len(node_ids)
    if num_nodes == 0:
        return None, None
        
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

    # Closed-form calibration optimization
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
