"""
PyTorch-based 3D DBSCAN with integrated EKF tracking
"""

import numpy as np
import torch
from typing import Optional, Tuple, Dict
from collections import defaultdict

# Measurement noise parameters
pi = np.pi
sigma_range = 0.035
sigma_doppler = 0.2
sigma_azimuth = pi / 4

measurement_noise = np.array(
    [[sigma_range**2, 0, 0], [0, sigma_doppler**2, 0], [0, 0, sigma_azimuth**2]]
)

# Import EKF
import sys
sys.path.append('new_pipe')
from Node.test.shim.new_pipe.ekf_custom import default_rda_EKF, cartesian_to_rda, rda_to_cartesian

# ========== TRACK MANAGEMENT PARAMETERS ==========
ASSOCIATION_THRESHOLD_RANGE = 2.0      # meters
ASSOCIATION_THRESHOLD_DOPPLER = 0.5    # m/s
ASSOCIATION_THRESHOLD_ANGLE = 0.3      # radians
MAX_MISSED_DETECTIONS = 5              # frames
MIN_TRACK_AGE = 3                      # frames before output
TRACK_DT = 0.1                         # time step (seconds)


class DBSCAN3D:
    """3D DBSCAN with integrated EKF tracking"""
    
    def __init__(
        self,
        eps: float = 1.5,
        min_samples: int = 3,
        device: str = "cuda" if torch.cuda.is_available() else "cpu",
    ):
        self.eps = eps
        self.min_samples = min_samples
        self.device = device
        
        # Track management
        self.active_tracks = {}
        self.next_track_id = 0
        self.frame_count = 0
        
    def _associate_clusters_to_tracks(self, cluster_centroids):
        """
        Associate cluster centroids to existing tracks using nearest-neighbor.
        
        Args:
            cluster_centroids: List of centroids in RDA format [range, doppler, angle]
            
        Returns:
            matched_pairs: list of (centroid_idx, track_id)
            unmatched_centroids: list of centroid indices
            unmatched_tracks: list of track_ids
        """
        if len(cluster_centroids) == 0 or len(self.active_tracks) == 0:
            return [], list(range(len(cluster_centroids))), list(self.active_tracks.keys())
        
        # Build cost matrix
        cost_matrix = np.zeros((len(cluster_centroids), len(self.active_tracks)))
        track_ids = list(self.active_tracks.keys())
        
        for i, centroid in enumerate(cluster_centroids):
            meas_range, meas_doppler, meas_angle = centroid[0], centroid[1], centroid[2]
            
            for j, track_id in enumerate(track_ids):
                tracker = self.active_tracks[track_id]['tracker']
                predicted_state = tracker.get_state()
                pred_rda = cartesian_to_rda(predicted_state[0], predicted_state[2],
                                           predicted_state[1], predicted_state[3])
                pred_range, pred_doppler, pred_angle = pred_rda[0], pred_rda[1], pred_rda[2]
                
                # Normalized distance
                range_dist = abs(meas_range - pred_range) / ASSOCIATION_THRESHOLD_RANGE
                doppler_dist = abs(meas_doppler - pred_doppler) / ASSOCIATION_THRESHOLD_DOPPLER
                angle_dist = abs(meas_angle - pred_angle) / ASSOCIATION_THRESHOLD_ANGLE
                angle_dist = min(angle_dist, abs(angle_dist - 2*np.pi))
                
                cost_matrix[i, j] = range_dist + doppler_dist + angle_dist
        
        # Greedy matching
        matched_pairs = []
        unmatched_centroids = list(range(len(cluster_centroids)))
        unmatched_tracks = track_ids.copy()
        
        while unmatched_centroids and unmatched_tracks:
            min_cost = float('inf')
            best_centroid_idx = None
            best_track_idx = None
            
            for c_idx in unmatched_centroids:
                for t_idx, track_id in enumerate(unmatched_tracks):
                    if cost_matrix[c_idx, track_ids.index(track_id)] < min_cost:
                        min_cost = cost_matrix[c_idx, track_ids.index(track_id)]
                        best_centroid_idx = c_idx
                        best_track_idx = t_idx
            
            if min_cost > 3.0:  # threshold
                break
            
            matched_pairs.append((best_centroid_idx, unmatched_tracks[best_track_idx]))
            unmatched_centroids.remove(best_centroid_idx)
            unmatched_tracks.pop(best_track_idx)
        
        return matched_pairs, unmatched_centroids, unmatched_tracks
    
    def _predict_tracks(self, dt):
        """Predict all active tracks forward in time"""
        for track_id in self.active_tracks:
            self.active_tracks[track_id]['tracker'].predict(dt)
    
    def _update_tracks(self, matched_pairs, cluster_centroids):
        """Update tracks with matched measurements"""
        for centroid_idx, track_id in matched_pairs:
            centroid = cluster_centroids[centroid_idx]
            measurement = np.array([centroid[0], centroid[1], centroid[2]])
            self.active_tracks[track_id]['tracker'].update(measurement)
            self.active_tracks[track_id]['last_seen'] = self.frame_count
            self.active_tracks[track_id]['age'] += 1
    
    def _initialize_new_tracks(self, unmatched_centroids, cluster_centroids):
        """Create new tracks for unmatched clusters"""
        for centroid_idx in unmatched_centroids:
            centroid = cluster_centroids[centroid_idx]
            initial_state = rda_to_cartesian(centroid[0], centroid[1], centroid[2])
            new_tracker = default_rda_EKF(initial_state=initial_state)
            
            self.active_tracks[self.next_track_id] = {
                'tracker': new_tracker,
                'last_seen': self.frame_count,
                'age': 1
            }
            self.next_track_id += 1
    
    def _delete_stale_tracks(self, unmatched_tracks):
        """Remove tracks that haven't been updated"""
        tracks_to_delete = []
        for track_id in unmatched_tracks:
            if self.frame_count - self.active_tracks[track_id]['last_seen'] > MAX_MISSED_DETECTIONS:
                tracks_to_delete.append(track_id)
        
        for track_id in tracks_to_delete:
            del self.active_tracks[track_id]
    
    def _extract_tracked_states(self):
        """Extract mature track states in Cartesian coordinates"""
        tracked_states = []
        for track_id in self.active_tracks:
            if self.active_tracks[track_id]['age'] >= MIN_TRACK_AGE:
                state = self.active_tracks[track_id]['tracker'].get_state()
                tracked_states.append(state)  # [x, vx, y, vy]
        
        return np.array(tracked_states) if tracked_states else np.array([]).reshape(0, 4)
    
    def fit_predict_with_tracking(self, X: np.ndarray,dt) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Perform DBSCAN clustering and EKF tracking in one pass.
        
        Args:
            X: Detection coordinates (N, 3) in [range, doppler, angle]
            
        Returns:
            labels: Cluster labels for each detection
            centroids_rda: Cluster centroids in RDA format (C, 3)
            centroids_ekf: EKF-tracked states in Cartesian (T, 4) [x, vx, y, vy]
        """
        self.frame_count += 1
        
        if len(X) == 0:
            # No detections - just predict existing tracks
            self._predict_tracks(dt)
            self._delete_stale_tracks(list(self.active_tracks.keys()))
            return np.array([]), np.array([]).reshape(0, 3), self._extract_tracked_states()
        
        # Convert to tensor
        X_tensor = torch.from_numpy(X).float().to(self.device)
        
        # Compute pairwise Mahalanobis distances
        cov_inv = torch.from_numpy(np.linalg.inv(measurement_noise)).float().to(self.device)
        diff = X_tensor.unsqueeze(1) - X_tensor.unsqueeze(0)
        dist = torch.sqrt(torch.sum(diff @ cov_inv * diff, dim=-1))
        
        # DBSCAN clustering
        labels = torch.full((len(X_tensor),), -1, dtype=torch.int32, device=self.device)
        cluster_id = 0
        
        for i in range(len(X_tensor)):
            if labels[i] != -1:
                continue
            
            neighbors = torch.where(dist[i] <= self.eps)[0]
            if len(neighbors) < self.min_samples:
                continue
            
            labels[i] = cluster_id
            seed_set = neighbors.tolist()
            
            j = 0
            while j < len(seed_set):
                q = seed_set[j]
                if labels[q] == -1:
                    labels[q] = cluster_id
                elif labels[q] != -1:
                    j += 1
                    continue
                
                neighbors_q = torch.where(dist[q] <= self.eps)[0]
                if len(neighbors_q) >= self.min_samples:
                    for neighbor in neighbors_q:
                        if neighbor not in seed_set:
                            seed_set.append(neighbor.item())
                j += 1
            
            cluster_id += 1
        
        labels_np = labels.cpu().numpy()
        
        # Compute cluster centroids in RDA space
        cluster_centroids = []
        for cid in range(cluster_id):
            cluster_mask = labels_np == cid
            if np.sum(cluster_mask) > 0:
                centroid = np.mean(X[cluster_mask], axis=0)
                cluster_centroids.append(centroid)
        
        # ========== EKF TRACKING PIPELINE ==========
        # 1. Predict all tracks
        self._predict_tracks()
        
        # 2. Associate clusters to tracks
        matched_pairs, unmatched_centroids, unmatched_tracks = self._associate_clusters_to_tracks(
            cluster_centroids
        )
        
        # 3. Update matched tracks
        self._update_tracks(matched_pairs, cluster_centroids)
        
        # 4. Initialize new tracks
        self._initialize_new_tracks(unmatched_centroids, cluster_centroids)
        
        # 5. Delete stale tracks
        self._delete_stale_tracks(unmatched_tracks)
        
        # 6. Extract tracked states
        centroids_ekf = self._extract_tracked_states()
        
        centroids_rda = np.array(cluster_centroids) if cluster_centroids else np.array([]).reshape(0, 3)
        
        return labels_np, centroids_rda, centroids_ekf


# ========== PROCESS FUNCTIONS ==========

def dbscan_ekf_process(detection_coords_3d, output_shape,dt):
    """
    Run 3D DBSCAN with integrated tracking and return 2D visualization + centroids.
    
    Returns:
        dbscan_data_2d: 2D map for visualization
        dbscan_angles: Angle map for visualization
        centroids_rda: Cluster centroids in RDA
        centroids_ekf: EKF-tracked states in Cartesian
    """
    if len(detection_coords_3d) == 0:
        return (
            np.zeros(output_shape, dtype=np.int32),
            np.zeros(output_shape, dtype=np.float32),
            np.array([]).reshape(0, 3),
            np.array([]).reshape(0, 4),
        )
    
    # Global DBSCAN instance with tracking state
    global _dbscan_tracker
    if '_dbscan_tracker' not in globals():
        _dbscan_tracker = DBSCAN3D(eps=1.5, min_samples=3, device='cpu')
    
    # Run clustering + tracking
    labels, centroids_rda, centroids_ekf = _dbscan_tracker.fit_predict_with_tracking(detection_coords_3d,dt)
    
    # Create 2D visualization maps
    dbscan_data_2d = np.zeros(output_shape, dtype=np.int32)
    dbscan_angles = np.zeros(output_shape, dtype=np.float32)
    
    for i, (r, d, a) in enumerate(detection_coords_3d):
        if labels[i] >= 0:
            r_idx, d_idx = int(r), int(d)
            if 0 <= r_idx < output_shape[0] and 0 <= d_idx < output_shape[1]:
                dbscan_data_2d[r_idx, d_idx] = labels[i] + 1
                dbscan_angles[r_idx, d_idx] = a
    
    return dbscan_data_2d, dbscan_angles, centroids_rda, centroids_ekf


def centroid_map(centroids_rda, output_shape):
    """
    Convert RDA centroids to 2D map visualization.
    """
    if len(centroids_rda) == 0:
        return np.zeros(output_shape, dtype=np.float32), np.zeros(output_shape, dtype=np.float32)
    
    centroids_map = np.zeros(output_shape, dtype=np.float32)
    centroids_angles = np.zeros(output_shape, dtype=np.float32)
    
    for centroid in centroids_rda:
        r_idx, d_idx = int(centroid[0]), int(centroid[1])
        if 0 <= r_idx < output_shape[0] and 0 <= d_idx < output_shape[1]:
            centroids_map[r_idx, d_idx] = 255
            centroids_angles[r_idx, d_idx] = centroid[2]
    
    return centroids_map, centroids_angles