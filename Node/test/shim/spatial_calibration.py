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
# Closed-form calibration (same as before)
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
        return None, None
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
        P_opt, theta_opt = closed_form_calibration(calibration_data)
        if P_opt is not None:
            node_ids = list(calibration_data.keys())
            trajectory = np.zeros((len(node_ids), len(frames)), dtype=np.complex64)
            for i, node_id in enumerate(node_ids):
                for t in range(len(frames)):
                    dets = calibration_data[node_id][t]
                    if dets.size == 0:
                        trajectory[i, t] = np.nan
                    else:
                        mean_range = np.mean(dets[:,0])
                        mean_angle = np.mean(dets[:,2])
                        trajectory[i, t] = mean_range * np.exp(1j * mean_angle)
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
    sio.connect('http://127.0.0.1:5001')
    sio.wait()
import os
import glob
import pickle
import numpy as np
import matplotlib.pyplot as plt

def load_centroid_data():
    """
    Loads centroid data from all node pickle files in the current directory.
    Returns:
        node_ids: list of node names
        frame_nums: list of synchronized frame numbers
        trajectories: np.ndarray shape (num_nodes, num_frames), complex positions
    """
    files = sorted(glob.glob("calibration_data_*.pkl"))
    node_ids = [os.path.splitext(os.path.basename(f))[0].split('_')[-1] for f in files]
    node_data = {}
    for fname, node_id in zip(files, node_ids):
        with open(fname, 'rb') as f:
            node_data[node_id] = pickle.load(f)
    # Find synchronized frames
    frame_sets = [set(d.keys()) for d in node_data.values()]
    common_frames = sorted(list(set.intersection(*frame_sets)))
    if not common_frames:
        raise RuntimeError("No synchronized frames found across all nodes.")
    # Build trajectory matrix
    num_nodes = len(node_ids)
    num_frames = len(common_frames)
    trajectories = np.zeros((num_nodes, num_frames), dtype=np.complex64)
    for i, node_id in enumerate(node_ids):
        for j, frame_num in enumerate(common_frames):
            centroids = node_data[node_id][frame_num]
            if centroids.size == 0:
                trajectories[i, j] = np.nan
            else:
                # Use mean range and angle for each frame
                mean_range = np.mean(centroids[:,0])
                mean_angle = np.mean(centroids[:,2])
                trajectories[i, j] = mean_range * np.exp(1j * mean_angle)
    # Remove frames with NaN
    valid_mask = ~np.isnan(trajectories).any(axis=0)
    trajectories = trajectories[:, valid_mask]
    frame_nums = [f for i, f in enumerate(common_frames) if valid_mask[i]]
    return node_ids, frame_nums, trajectories

def closed_form_calibration(trajectory):
    num_radars, num_frames = trajectory.shape
    P_opt = np.zeros((num_radars, num_radars), dtype=complex)
    theta_opt = np.zeros((num_radars, num_radars))
    for i in range(num_radars):
        for k in range(num_radars):
            z_i = trajectory[i, :]
            z_k = trajectory[k, :]
            z_i_mean = np.mean(z_i)
            z_k_mean = np.mean(z_k)
            val = np.sum((z_k - z_k_mean) * np.conj(z_i - z_i_mean))
            phi = np.arctan2(val.imag, val.real)
            theta_opt[i, k] = np.rad2deg(-phi)
            P_opt[i, k] = z_i_mean - np.exp(-1j * phi) * z_k_mean
    return P_opt, theta_opt

def visualize(trajectory, P_opt, theta_opt, node_ids, output_dir):
    num_radars = trajectory.shape[0]
    os.makedirs(output_dir, exist_ok=True)
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

def save_results(P_opt, theta_opt, node_ids, output_dir):
    filename = os.path.join(output_dir, 'calibration_results.txt')
    with open(filename, 'w') as f:
        f.write("="*60 + "\n")
        f.write("RADAR CALIBRATION RESULTS\n")
        f.write("="*60 + "\n\n")
        for i, ref_node in enumerate(node_ids):
            f.write(f"{ref_node} as Reference:\n")
            f.write("-"*50 + "\n")
            for k, node in enumerate(node_ids):
                if i != k:
                    f.write(f"  {node}: Position=({P_opt[i,k].real:.2f}, {P_opt[i,k].imag:.2f})m, "
                           f"Orientation={theta_opt[i,k]:.1f}°\n")
            f.write("\n")
    print(f"Results saved: {filename}")

def main():
    output_dir = 'calibration_output'
    print("Loading centroid data from all nodes...")
    node_ids, frame_nums, trajectory = load_centroid_data()
    print(f"Loaded {len(node_ids)} nodes, {trajectory.shape[1]} synchronized frames.")
    print("Running spatial calibration...")
    P_opt, theta_opt = closed_form_calibration(trajectory)
    print("Saving calibration results...")
    save_results(P_opt, theta_opt, node_ids, output_dir)
    print("Generating visualizations...")
    visualize(trajectory, P_opt, theta_opt, node_ids, output_dir)
    print("Calibration complete. Results in calibration_output/")

if __name__ == "__main__":
    main()
