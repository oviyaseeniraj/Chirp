"""
Pure NumPy and Scikit-Learn based 3D DBSCAN implementation.
Optimized for CPU execution, eliminating PyTorch dispatch overhead and synchronization.
"""

from typing import Optional, Tuple, Dict
import time
import numpy as np
import torch
from sklearn.metrics import pairwise_distances

from .. import config


class DBSCAN3D:
    """
    3D DBSCAN clustering algorithm implemented in pure NumPy for CPU efficiency.

    Parameters:
    -----------
    eps : float
        The maximum distance between two samples for one to be considered
        as in the neighborhood of the other.
    min_samples : int
        The number of samples in a neighborhood for a point to be considered
        as a core point.
    metric : str
        The distance metric to use. Options: 'euclidean', 'cosine', 'manhattan', 'mahalanobis'
    scale_coords : bool
        Whether to normalize coordinates to balance the 3D aspect ratio.
    x_weight, y_weight, z_weight : float
        Weight multipliers for dimensions.
    measurement_noise_matrix : np.ndarray, optional
        3x3 measurement noise covariance matrix for Mahalanobis distance.
    """

    def __init__(
        self,
        eps: float = 0.5,
        min_samples: int = 5,
        metric: str = "euclidean",
        scale_coords: bool = True,
        x_weight: float = 1.0,
        y_weight: float = 1.0,
        z_weight: float = 1.0,
        measurement_noise_matrix: Optional[np.ndarray] = None,
    ):
        self.eps = eps
        self.min_samples = min_samples
        self.metric = metric
        self.scale_coords = scale_coords
        self.x_weight = x_weight
        self.y_weight = y_weight
        self.z_weight = z_weight

        # Initialize Mahalanobis distance matrix
        if measurement_noise_matrix is None:
            self.measurement_noise_matrix = np.eye(3)
        else:
            self.measurement_noise_matrix = np.array(measurement_noise_matrix, dtype=np.float32)

        # Precompute inverse for efficiency
        self.measurement_noise_matrix_inv = np.linalg.inv(self.measurement_noise_matrix)

        self.labels_ = None
        self.core_sample_indices_ = None
        self.n_clusters_ = 0

    def _compute_distance_matrix(self, X: np.ndarray) -> np.ndarray:
        """Pairwise distance matrix using Scikit-Learn's optimized CPU implementation."""
        if self.metric == "mahalanobis":
            return pairwise_distances(X, metric="mahalanobis", VI=self.measurement_noise_matrix_inv)
        return pairwise_distances(X, metric=self.metric)

    def fit(self, detection_coords: np.ndarray) -> "DBSCAN3D":
        """Perform DBSCAN clustering on 3D detection coordinates using NumPy."""
        # Drop-in compatibility: convert if input is torch tensor
        if hasattr(detection_coords, "detach"):
            detection_coords = detection_coords.detach().cpu().numpy()
        else:
            detection_coords = np.array(detection_coords, dtype=np.float32)

        n_samples = detection_coords.shape[0]
        if n_samples == 0:
            self.labels_ = np.array([], dtype=np.int64)
            self.n_clusters_ = 0
            return self

        # Coordinate transformations (Angular to Spatial Frequency)
        coords = detection_coords.copy()
        coords[:, 2] = np.deg2rad(coords[:, 2])
        coords[:, 2] = np.pi * np.sin(coords[:, 2])

        # Scale coordinates
        if self.scale_coords:
            coords[:, 0] *= self.x_weight
            coords[:, 1] *= self.y_weight
            coords[:, 2] *= self.z_weight

        # Compute distance matrix and find core points
        distances = self._compute_distance_matrix(coords)
        neighbors_mask = distances <= self.eps
        neighbor_counts = neighbors_mask.sum(axis=1)
        is_core = neighbor_counts >= self.min_samples
        core_indices = np.where(is_core)[0]
        self.core_sample_indices_ = core_indices

        # Clustering loop
        labels = np.full(n_samples, -1, dtype=np.int64)
        visited = np.zeros(n_samples, dtype=bool)
        current_cluster = 1

        for core_idx in core_indices:
            if visited[core_idx] or labels[core_idx] != -1:
                continue

            visited[core_idx] = True
            labels[core_idx] = current_cluster
            
            # BFS/DFS search
            seeds = list(np.where(neighbors_mask[core_idx])[0])
            seed_set = set(seeds)
            
            while seed_set:
                curr = seed_set.pop()
                if visited[curr]:
                    continue
                visited[curr] = True
                
                if labels[curr] == -1:
                    labels[curr] = current_cluster
                    if is_core[curr]:
                        new_neighbors = np.where(neighbors_mask[curr])[0]
                        for n in new_neighbors:
                            if not visited[n]:
                                seed_set.add(n)
            
            current_cluster += 1

        # Centroid calculation
        self.cluster_centroids_ = {}
        for cid in range(1, current_cluster):
            mask = labels == cid
            pts = detection_coords[mask]
            if len(pts) > 0:
                # Weighted geometry
                wx = np.mean(pts[:, 0])
                wy = np.mean(pts[:, 1])
                # Circular mean handle
                angles = np.deg2rad(pts[:, 2])
                wa = np.arctan2(np.mean(np.sin(angles)), np.mean(np.cos(angles)))
                
                # Wrap in torch tensor for pipeline compatibility
                self.cluster_centroids_[cid] = (
                    torch.from_numpy(np.array([wx, wy, wa], dtype=np.float32)),
                    len(pts)
                )

        self.labels_ = labels
        self.n_clusters_ = current_cluster
        return self

    def fit_predict(self, detection_coords: np.ndarray) -> np.ndarray:
        if len(detection_coords) == 0:
            return np.array([], dtype=np.int32)
        
        self.fit(detection_coords)
        output_labels = self.labels_.copy()
        noise_idx = self.n_clusters_
        
        # Noise assignment
        noise_mask = output_labels == -1
        n_noise = np.sum(noise_mask)
        if n_noise > 0:
            output_labels[noise_mask] = np.arange(noise_idx, noise_idx + n_noise)
            
        return output_labels.astype(np.int32)


def dbscan_cluster_3d(detection_coords, **kwargs):
    clusterer = DBSCAN3D(**kwargs)
    return clusterer.fit_predict(detection_coords), clusterer.n_clusters_, clusterer.cluster_centroids_


def dbscan_process(detection_coords, shape):
    """CPU Version of dbscan_process using pure NumPy."""
    if len(detection_coords) > 0:
        cluster_labels_3d, n_clusters, centroids = dbscan_cluster_3d(
            detection_coords,
            eps=3.0,
            min_samples=10,
            metric="mahalanobis",
            scale_coords=True,
            x_weight=config.SIGMA_RANGE,
            y_weight=config.SIGMA_DOPPLER,
            z_weight=config.SIGMA_AZIMUTH,
            measurement_noise_matrix=config.MEASUREMENT_NOISE
        )

        dbscan_data_2d = np.zeros(shape, dtype=np.int32)
        dbscan_angles = np.zeros(shape, dtype=np.float32)

        for coord, label in zip(detection_coords, cluster_labels_3d):
            ridx, didx = int(coord[0]), int(coord[1])
            if 0 <= didx < shape[0] and 0 <= ridx < shape[1]:
                dbscan_data_2d[didx, ridx] = label
                dbscan_angles[didx, ridx] = coord[2]
    else:
        dbscan_data_2d = np.zeros(shape, dtype=np.int32)
        dbscan_angles = np.zeros(shape, dtype=np.float32)
        centroids = {}

    dbscan_data_2d[32, :] = 0
    dbscan_angles[32, :] = 0
    return dbscan_data_2d, dbscan_angles, centroids


def centroid_process(centroids, shape):
    """CPU Version of centroid_process using pure NumPy."""
    centroids_map = np.zeros(shape, dtype=np.int32)
    centroids_angles = np.zeros(shape, dtype=np.float32)

    if len(centroids) > 0:
        for label, (c_vec, _) in centroids.items():
            ridx, didx = int(np.round(c_vec[0])), int(np.round(c_vec[1]))
            ridx = np.clip(ridx, 0, shape[1] - 1)
            didx = np.clip(didx, 0, shape[0] - 1)
            
            centroids_map[didx, ridx] = label
            centroids_angles[didx, ridx] = np.rad2deg(c_vec[2])

    centroids_map[32, :] = 0
    centroids_angles[32, :] = 0
    return centroids_map, centroids_angles
