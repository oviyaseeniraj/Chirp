import os
import numpy as np
import matplotlib.pyplot as plt
import socketio
import threading
from collections import defaultdict

# Real-time calibration manager
class RealTimeCalibrationManager:
    def __init__(self, num_nodes=4, calibration_window=50, output_dir='calibration_output'):
        self.num_nodes = num_nodes
        self.calibration_window = calibration_window
        self.output_dir = output_dir
        self.node_data = defaultdict(lambda: defaultdict(list))  # node_id -> frame_num -> centroids
        self.lock = threading.Lock()
        os.makedirs(output_dir, exist_ok=True)
    def add_detection(self, node_id, frame_num, centroids):
        with self.lock:
            self.node_data[node_id][frame_num].append(centroids)
    def check_ready(self):
        with self.lock:
            frame_sets = [set(frames.keys()) for frames in self.node_data.values()]
            if len(frame_sets) < self.num_nodes:
                return None
            common_frames = set.intersection(*frame_sets)
            if len(common_frames) >= self.calibration_window:
                return sorted(list(common_frames))[-self.calibration_window:]
            return None
    def get_calibration_data(self, frames):
        with self.lock:
            calibration_data = {}
            for node_id in self.node_data:
                calibration_data[node_id] = []
                for frame_num in frames:
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
    node_ids = list(calibration_data.keys())
    num_nodes = len(node_ids)
    num_frames = len(calibration_data[node_ids[0]])
    trajectory = np.zeros((num_nodes, num_frames), dtype=np.complex64)
    for i, node_id in enumerate(node_ids):
        for t in range(num_frames):
            dets = calibration_data[node_id][t]
            if dets.size == 0:
                trajectory[i, t] = np.nan
            else:
                mean_range = np.mean(dets[:,0])
                mean_angle = np.mean(dets[:,2])
                trajectory[i, t] = mean_range * np.exp(1j * mean_angle)
    valid_mask = ~np.isnan(trajectory).any(axis=0)
    trajectory = trajectory[:, valid_mask]
    num_frames = trajectory.shape[1]
    if num_frames == 0:
        return None, None, None
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
    return P_opt, theta_opt, trajectory

def visualize(trajectory, P_opt, theta_opt, node_ids, output_dir):
    num_radars = trajectory.shape[0]
    for ref in range(num_radars):
        plt.figure(figsize=(10, 8))
        plt.plot(trajectory[ref, :].real, trajectory[ref, :].imag, 'b-', alpha=0.3, label=f'{node_ids[ref]} Trajectory')
        plt.scatter(P_opt[ref, :].real, P_opt[ref, :].imag, s=200, c='red', marker='X', zorder=10)
        for i in range(num_radars):
            angle_rad = np.deg2rad(theta_opt[ref, i])
            dx = 5 * np.cos(angle_rad)
            dy = 5 * np.sin(angle_rad)
            plt.arrow(P_opt[ref, i].real, P_opt[ref, i].imag, dx, dy, head_width=2, color='black', zorder=5)
            plt.text(P_opt[ref, i].real, P_opt[ref, i].imag + 3, node_ids[i], ha='center', fontsize=10)
        plt.grid(True)
        plt.gca().set_aspect('equal', adjustable='box')
        plt.xlabel('X (meters)')
        plt.ylabel('Y (meters)')
        plt.title(f'Calibration Results - {node_ids[ref]} Reference Frame')
        plt.legend()
        filename = os.path.join(output_dir, f'calibration_{node_ids[ref]}.png')
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"Saved: {filename}")

def calibration_callback(manager, node_id, frame_num, centroids):
    manager.add_detection(node_id, frame_num, centroids)
    frames = manager.check_ready()
    if frames:
        calibration_data = manager.get_calibration_data(frames)
        P_opt, theta_opt, trajectory = closed_form_calibration(calibration_data)
        if P_opt is not None:
            node_ids = list(calibration_data.keys())
            visualize(trajectory, P_opt, theta_opt, node_ids, manager.output_dir)
            print("Calibration complete. Visualizations updated.")
            manager.clear_calibration_frames(frames)

# Socket.IO client for real-time data
sio = socketio.Client()
manager = RealTimeCalibrationManager()
@sio.event
def connect():
    print("Connected to data stream.")
@sio.on('send_frame')
def on_send_frame(data):
    # Example: data = { 'node_id': 'node1', 'frame_num': 123, 'centroids': ... }
    node_id = data.get('node_id', 'unknown')
    frame_num = data.get('frame_num', -1)
    centroids_bytes = data.get('centroids', None)
    if centroids_bytes is not None:
        centroids = np.frombuffer(centroids_bytes, dtype=np.float32).reshape(-1, 3)
        calibration_callback(manager, node_id, frame_num, centroids)
@sio.event
def disconnect():
    print("Disconnected from data stream.")
if __name__ == "__main__":
    # Connect to all node Socket.IO servers for spatial calibration
    NODE_IPS = [
        '169.231.200.9',  # tien1
        '169.231.86.85',  # tien3
        '169.231.105.114' # tien4
    ]
    for ip in NODE_IPS:
        try:
            sio.connect(f'http://{ip}:5001')
            print(f"Connected to node server at {ip}:5001")
        except Exception as e:
            print(f"Failed to connect to node server at {ip}:5001: {e}")
    sio.wait()
