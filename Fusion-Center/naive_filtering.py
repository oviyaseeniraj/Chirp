#!/usr/bin/env python3
import os
import pickle
import numpy as np
import matplotlib.pyplot as plt
import sys
import glob
from collections import deque

# Add project root to path to access config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from Node.src.radar import config
except ImportError:
    class MockConfig:
        RANGE_RES = 0.04
        VELOCITY_RES = 0.1
        SLOW_TIME = 64
    config = MockConfig()

class NaiveFilter:
    def __init__(self, alpha=0.3, window_size=5, pos_threshold=1.2, vel_threshold=2.5):
        self.alpha = alpha
        self.window_size = window_size
        self.pos_threshold = pos_threshold
        self.vel_threshold = vel_threshold
        
        # State: deque of recent (x, y) and (vx, vy)
        self.pos_history = deque(maxlen=window_size)
        self.vel_history = deque(maxlen=window_size)

    def filter_point(self, pos, vel):
        """
        Selective smoothing: 
        If pos/vel deviates too much from the window median, apply Alpha filter.
        Otherwise, use raw value.
        """
        smoothed_pos = pos
        smoothed_vel = vel
        is_pos_outlier = False
        is_vel_outlier = False

        # --- Position Smoothing ---
        if len(self.pos_history) == self.window_size:
            median_pos = np.median(list(self.pos_history), axis=0)
            dist = np.linalg.norm(pos - median_pos)
            
            if dist > self.pos_threshold:
                is_pos_outlier = True
                avg_pos = np.mean(list(self.pos_history), axis=0)
                smoothed_pos = self.alpha * pos + (1 - self.alpha) * avg_pos
        
        # --- Velocity Smoothing ---
        if len(self.vel_history) == self.window_size:
            median_vel = np.median(list(self.vel_history), axis=0)
            v_diff = np.linalg.norm(vel - median_vel)
            
            if v_diff > self.vel_threshold:
                is_vel_outlier = True
                avg_vel = np.mean(list(self.vel_history), axis=0)
                smoothed_vel = self.alpha * vel + (1 - self.alpha) * avg_vel

        # Update buffers
        self.pos_history.append(smoothed_pos)
        self.vel_history.append(smoothed_vel)
        
        return smoothed_pos, smoothed_vel, is_pos_outlier

    # Alias so NaiveFilter conforms to TrackerBase used by animate_centroids.py
    def update(self, pos, vel):
        return self.filter_point(pos, vel)

def polar_to_cartesian(range_idx, angle_rad):
    r = range_idx * config.RANGE_RES
    px = r * np.sin(angle_rad)
    py = r * np.cos(angle_rad)
    return px, py

def process_naive_filtering(input_file):
    with open(input_file, 'rb') as f:
        node_data = pickle.load(f)

    results = {}
    for node_id, frames in node_data.items():
        print(f"Naive filtering node: {node_id} ({len(frames)} frames)")
        
        # Looser thresholds to avoid flagging normal movement
        n_filter = NaiveFilter(alpha=0.1, window_size=5, pos_threshold=1.2, vel_threshold=3.0)
        smoothed_path = []
        raw_path = []
        outlier_flags = []
        last_xy = None

        for frame in frames:
            detections = frame.get('clusters', [])
            if not detections: continue
                
            candidates = []
            for c in detections:
                px, py = polar_to_cartesian(c['range_idx'], c['angle_rad'])
                v_rad = (c['doppler_idx'] - config.SLOW_TIME // 2) * config.VELOCITY_RES
                vx = v_rad * np.sin(c['angle_rad'])
                vy = v_rad * np.cos(c['angle_rad'])
                candidates.append((np.array([px, py]), np.array([vx, vy])))

            if last_xy is None:
                match_pos, match_vel = candidates[0]
            else:
                dists = [np.linalg.norm(cand[0] - last_xy) for cand in candidates]
                idx = np.argmin(dists)
                match_pos, match_vel = candidates[idx]

            s_pos, s_vel, is_outlier = n_filter.filter_point(match_pos, match_vel)
            
            raw_path.append(np.concatenate([match_pos, match_vel]))
            smoothed_path.append(np.concatenate([s_pos, s_vel]))
            outlier_flags.append(is_outlier)
            last_xy = s_pos

        results[node_id] = {
            'smoothed': np.array(smoothed_path),
            'raw': np.array(raw_path),
            'outliers': np.array(outlier_flags)
        }

    return results

def plot_results(results, output_path):
    plt.figure(figsize=(12, 10))
    
    for node_id, data in results.items():
        raw = data['raw']
        smoothed = data['smoothed']
        outliers = data['outliers']
        
        # Position Plot
        plt.subplot(2, 1, 1)
        # Plot raw as faint gray background
        plt.scatter(raw[:, 0], raw[:, 1], alpha=0.1, label="All Raw", s=10, color='gray')
        
        # Plot inliers (where raw == smoothed)
        inlier_mask = ~outliers
        if np.any(inlier_mask):
            plt.scatter(raw[inlier_mask, 0], raw[inlier_mask, 1], alpha=0.8, label="Raw Inliers", s=20, color='blue')
        
        # Plot smoothed outliers in red
        if np.any(outliers):
            plt.scatter(smoothed[outliers, 0], smoothed[outliers, 1], alpha=0.8, label="Smoothed Outliers", s=30, color='red', marker='x')
        
        # Connect with a line to show the "flow"
        plt.plot(smoothed[:, 0], smoothed[:, 1], color='green', alpha=0.4, linewidth=1, label="Trajectory Path")
        
        plt.title(f"Position Filtering (Blue=Raw, Red=Smoothed Outlier): {node_id}")
        plt.xlabel("Lateral (m)")
        plt.ylabel("Range (m)")
        plt.legend()
        plt.grid(True)
        plt.axis('equal')

        # Velocity Plot
        plt.subplot(2, 1, 2)
        raw_v_mag = np.linalg.norm(raw[:, 2:4], axis=1)
        smooth_v_mag = np.linalg.norm(smoothed[:, 2:4], axis=1)
        
        plt.plot(raw_v_mag, alpha=0.2, label="Raw Velocity", color='gray')
        plt.scatter(np.where(inlier_mask)[0], raw_v_mag[inlier_mask], color='blue', s=10, alpha=0.5)
        plt.plot(smooth_v_mag, label="Smoothed Velocity", color='green')
        
        outlier_indices = np.where(outliers)[0]
        if len(outlier_indices) > 0:
            plt.scatter(outlier_indices, smooth_v_mag[outlier_indices], color='red', marker='x', s=30, label="Outlier Smooth Point")

        plt.title("Velocity Magnitude Comparison (Red Marker = Outlier Corrected)")
        plt.xlabel("Frame Index")
        plt.ylabel("Velocity (m/s)")
        plt.legend()
        plt.grid(True)

    print(f"Stats for {node_id}: {np.sum(outliers)} outliers detected out of {len(outliers)} frames ({100*np.sum(outliers)/len(outliers):.1f}%)")

    plt.tight_layout()
    plt.savefig(output_path)
    print(f"Naive filtering plot saved to {output_path}")

if __name__ == "__main__":
    temp_dir = os.path.join(os.path.dirname(__file__), "temp")
    files = glob.glob(os.path.join(temp_dir, "*.pkl"))
    if not files:
        print("No .pkl files found.")
        sys.exit(1)
    
    latest_file = max(files, key=os.path.getctime)
    print(f"Processing latest file: {latest_file}")
    
    results = process_naive_filtering(latest_file)
    
    output_png = os.path.join(temp_dir, "naive_filtering_results.png")
    plot_results(results, output_png)
