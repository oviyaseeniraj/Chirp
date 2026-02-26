"""
PyTorch-based 3D DBSCAN (Density-Based Spatial Clustering of Applications with Noise)
Implementation optimized for GPU acceleration with exposed critical parameters.

Input: Detection coordinates in 3D space
Output: Array with cluster labels (0 for background, 1-n for clusters)
"""

from typing import Optional, Tuple

import numpy as np
import torch
import torch.nn.functional as F

from .. import config


class DBSCAN3D:
    """
    3D DBSCAN clustering algorithm implemented in PyTorch for GPU acceleration.

    Parameters:
    -----------
    eps : float
        The maximum distance between two samples for one to be considered
        as in the neighborhood of the other. This is the most important DBSCAN parameter.
        Default: 0.5

    min_samples : int
        The number of samples in a neighborhood for a point to be considered
        as a core point. This includes the point itself.
        Default: 5

    metric : str
        The distance metric to use. Options: 'euclidean', 'cosine', 'manhattan', 'mahalanobis'
        Default: 'euclidean'

    scale_coords : bool
        Whether to normalize coordinates to balance the 3D aspect ratio.
        When True, coordinates are scaled so distances are balanced across dimensions.
        Default: True

    x_weight : float
        Weight multiplier for x dimension. Higher values make x distances more important.
        Only used when scale_coords=True.
        Default: 1.0

    y_weight : float
        Weight multiplier for y dimension. Higher values make y distances more important.
        Only used when scale_coords=True.
        Default: 1.0

    z_weight : float
        Weight multiplier for z dimension. Higher values make z distances more important.
        Only used when scale_coords=True.
        Default: 1.0

    measurement_noise_matrix : torch.Tensor or np.ndarray, optional
        3x3 measurement noise covariance matrix for Mahalanobis distance.
        If None, identity matrix is used. Only used when metric='mahalanobis'.
        Default: None (uses identity matrix)

    device : str or torch.device
        Device to run computations on ('cuda' or 'cpu')
        Default: 'cuda' if available, else 'cpu'
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
        measurement_noise_matrix: Optional[torch.Tensor] = None,
        device: Optional[str] = None,
    ):
        self.eps = eps
        self.eps_sq = eps * eps  # Pre-compute for euclidean (avoids sqrt)
        self.min_samples = min_samples
        self.metric = metric
        self.scale_coords = scale_coords
        self.x_weight = x_weight
        self.y_weight = y_weight
        self.z_weight = z_weight

        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)

        # Initialize Mahalanobis distance matrix
        if measurement_noise_matrix is None:
            self.measurement_noise_matrix = torch.eye(3, device=self.device)
        else:
            if isinstance(measurement_noise_matrix, np.ndarray):
                measurement_noise_matrix = torch.from_numpy(measurement_noise_matrix)
            self.measurement_noise_matrix = measurement_noise_matrix.float().to(
                self.device
            )

        # Precompute inverse for efficiency
        self.measurement_noise_matrix_inv = torch.linalg.inv(
            self.measurement_noise_matrix
        )

        self.labels_ = None
        self.core_sample_indices_ = None
        self.n_clusters_ = 0

    def _compute_distance_matrix(self, X: torch.Tensor) -> torch.Tensor:
        """
        Compute pairwise distance matrix based on the specified metric.
        Uses vectorized operations for speed.

        Parameters:
        -----------
        X : torch.Tensor of shape (n_samples, 3)
            Input data with 3D coordinates

        Returns:
        --------
        distances : torch.Tensor of shape (n_samples, n_samples)
            Pairwise distance matrix
        """
        if self.metric == "euclidean":
            # Efficient euclidean distance computation: ||a - b||^2 = ||a||^2 + ||b||^2 - 2<a,b>
            norms = (X**2).sum(dim=1, keepdim=True)
            distances_sq = norms + norms.T - 2 * torch.mm(X, X.T)
            # Clamp to avoid negative values from numerical errors, then sqrt
            distances_sq = torch.clamp(distances_sq, min=0)
            distances = torch.sqrt(distances_sq)

        elif self.metric == "cosine":
            # Cosine distance = 1 - cosine similarity
            X_normalized = F.normalize(X, p=2, dim=1)
            cosine_sim = torch.mm(X_normalized, X_normalized.T)
            distances = 1 - cosine_sim

        elif self.metric == "manhattan":
            # Manhattan distance (L1 norm)
            distances = torch.cdist(X, X, p=1)

        elif self.metric == "mahalanobis":
            # Mahalanobis distance: sqrt((x - y)^T * Sigma^-1 * (x - y))
            # Vectorized implementation
            n_samples = X.shape[0]
            diff = X.unsqueeze(1) - X.unsqueeze(0)  # (n_samples, n_samples, 3)

            # Apply Mahalanobis: (diff)^T * Sigma^-1 * (diff)
            mahal_inner = torch.einsum("ijk,kl->ijl", diff, self.measurement_noise_matrix_inv)
            mahal_sq = torch.sum(diff * mahal_inner, dim=2)  # (n_samples, n_samples)
            distances = torch.sqrt(torch.clamp(mahal_sq, min=0))

        else:
            raise ValueError(f"Unsupported metric: {self.metric}")

        return distances

    def _get_neighbors_mask(self, distances: torch.Tensor) -> torch.Tensor:
        """
        Find neighbors within eps distance for each point.
        Returns sparse neighbor information for efficiency.

        Parameters:
        -----------
        distances : torch.Tensor of shape (n_samples, n_samples)
            Pairwise distance matrix

        Returns:
        --------
        neighbors_mask : torch.Tensor of shape (n_samples, n_samples)
            Boolean mask where True indicates a neighbor relationship
        """
        return distances <= self.eps

    def fit(self, detection_coords: torch.Tensor) -> "DBSCAN3D":
        """
        Perform DBSCAN clustering on 3D detection coordinates.
        Optimized with vectorized operations and early termination.

        Parameters:
        -----------
        detection_coords : torch.Tensor of shape (n_detections, 3)
            Detection coordinates [x, y, z]

        Returns:
        --------
        self : DBSCAN3D
            Fitted estimator
        """
        if not isinstance(detection_coords, torch.Tensor):
            detection_coords = torch.tensor(detection_coords, dtype=torch.float32)

        detection_coords = detection_coords.to(self.device).clone()
        detection_coords[:, 2] = torch.deg2rad(detection_coords[:, 2])

        # Store original angles BEFORE spatial frequency transformation
        original_angles = detection_coords[:, 2].clone()

        # Apply spatial frequency transformation for clustering
        detection_coords[:, 2] = np.pi * torch.sin(original_angles)

        n_samples = detection_coords.shape[0]

        # Early exit for empty input
        if n_samples == 0:
            self.labels_ = torch.tensor([], dtype=torch.long, device=self.device)
            self.n_clusters_ = 0
            return self

        # Scale coordinates to balance aspect ratio if enabled
        if self.scale_coords:
            scaled_coords = detection_coords.clone()
            scaled_coords[:, 0] = scaled_coords[:, 0] * self.x_weight
            scaled_coords[:, 1] = scaled_coords[:, 1] * self.y_weight
            scaled_coords[:, 2] = scaled_coords[:, 2] * self.z_weight
        else:
            scaled_coords = detection_coords

        # Compute distance matrix
        distances = self._compute_distance_matrix(scaled_coords)

        # Find neighbors for each point (vectorized)
        neighbors_mask = self._get_neighbors_mask(distances)
        neighbor_counts = neighbors_mask.sum(dim=1)

        # Identify core points (points with at least min_samples neighbors)
        is_core = neighbor_counts >= self.min_samples
        core_indices = torch.where(is_core)[0]
        self.core_sample_indices_ = core_indices

        # Initialize labels (-1 means noise/unassigned internally)
        labels = torch.full((n_samples,), -1, dtype=torch.long, device=self.device)

        current_cluster = 1  # Start from 1 (0 reserved for background)
        visited = torch.zeros(n_samples, dtype=torch.bool, device=self.device)

        # Process only core points (optimization: skip non-core points initially)
        for core_idx in core_indices:
            core_idx_int = core_idx.item()

            if visited[core_idx_int] or labels[core_idx_int] != -1:
                continue

            # Start a new cluster
            visited[core_idx_int] = True
            labels[core_idx_int] = current_cluster

            # Find all density-reachable points (optimized BFS with torch operations)
            neighbor_indices = torch.where(neighbors_mask[core_idx_int])[0]
            seeds = set(neighbor_indices.cpu().numpy())

            while seeds:
                current_point = seeds.pop()

                if visited[current_point]:
                    continue

                visited[current_point] = True

                # Only assign if not already in a cluster
                if labels[current_point] == -1:
                    labels[current_point] = current_cluster

                    # If current point is a core point, add its neighbors to seeds
                    if is_core[current_point]:
                        new_neighbors = torch.where(neighbors_mask[current_point])[0]
                        new_seeds = set(new_neighbors.cpu().numpy())
                        seeds.update(new_seeds - set(visited.cpu().numpy().nonzero()[0]))

            current_cluster += 1

        # Compute cluster centroids using weighted coordinates
        self.cluster_centroids_ = {}
        for cluster_id in range(1, current_cluster):
            cluster_mask = labels == cluster_id
            cluster_points = detection_coords[cluster_mask]
            
            if len(cluster_points) > 0:
                # Weighted range (x-coordinate)
                weighted_x = torch.sum(cluster_points[:, 0] * self.x_weight) / torch.sum(
                    torch.ones(len(cluster_points), device=self.device) * self.x_weight
                )

                # Weighted Doppler velocity (y-coordinate)
                weighted_y = torch.sum(cluster_points[:, 1] * self.y_weight) / torch.sum(
                    torch.ones(len(cluster_points), device=self.device) * self.y_weight
                )

                # Weighted circular mean in spatial frequency domain
                frequencies = cluster_points[:, 2]  # Already in spatial frequency space
                weighted_freq = torch.mean(frequencies)

                # Convert spatial frequency back to angle
                weighted_angle = torch.arcsin(torch.clamp(weighted_freq / np.pi, -1.0, 1.0))

                self.cluster_centroids_[cluster_id] = (
                    torch.tensor(
                        [weighted_x.item(), weighted_y.item(), weighted_angle.item()],
                        device=self.device,
                    ),
                    len(cluster_points),
                )

        self.labels_ = labels
        self.n_clusters_ = current_cluster

        return self

    def fit_predict(self, detection_coords: np.ndarray) -> np.ndarray:
        """
        Fit the DBSCAN model and predict cluster labels.

        Parameters:
        -----------
        detection_coords : numpy array of shape (n_detections, 3)
            Detection coordinates [x, y, z]

        Returns:
        --------
        labels : numpy array of shape (n_detections,)
            Cluster labels (0 for background, 1-n for clusters, >n for noise points)
        """
        if len(detection_coords) == 0:
            return np.array([], dtype=np.int32)

        if detection_coords.ndim != 2 or detection_coords.shape[1] != 3:
            raise ValueError(f"Expected shape (n_detections, 3), got {detection_coords.shape}")

        # Perform DBSCAN clustering on coordinates
        self.fit(detection_coords)

        # Map internal labels: -1 (noise) -> sequential IDs after main clusters
        labels_cpu = self.labels_.cpu().numpy()
        output_labels = labels_cpu.copy()

        # Assign noise points to individual cluster IDs
        noise_cluster_id = self.n_clusters_
        for i in range(len(labels_cpu)):
            if labels_cpu[i] == -1:
                output_labels[i] = noise_cluster_id
                noise_cluster_id += 1

        return output_labels.astype(np.int32)

    def get_cluster_info(self) -> dict:
        """
        Get information about the clustering results.

        Returns:
        --------
        info : dict
            Dictionary containing clustering statistics
        """
        if self.labels_ is None:
            raise ValueError("Model has not been fitted yet. Call fit() first.")

        n_noise = (self.labels_ == -1).sum().item()
        cluster_sizes = []

        for cluster_id in range(1, self.n_clusters_):
            size = (self.labels_ == cluster_id).sum().item()
            cluster_sizes.append(size)

        return {
            "n_clusters": self.n_clusters_ - 1,
            "n_noise_points": n_noise,
            "cluster_sizes": cluster_sizes,
            "n_core_points": len(self.core_sample_indices_),
            "eps": self.eps,
            "min_samples": self.min_samples,
            "metric": self.metric,
            "scale_coords": self.scale_coords,
        }


def dbscan_cluster_3d(
    detection_coords: np.ndarray,
    eps: float = 0.5,
    min_samples: int = 5,
    metric: str = "euclidean",
    scale_coords: bool = True,
    x_weight: float = 1.0,
    y_weight: float = 1.0,
    z_weight: float = 1.0,
    measurement_noise_matrix: Optional[np.ndarray] = None,
    device: Optional[str] = None,
) -> Tuple[np.ndarray, int, dict]:
    """
    Convenience function to perform 3D DBSCAN clustering on detection coordinates.

    Parameters:
    -----------
    detection_coords : numpy array of shape (n_detections, 3)
        Detection coordinates [x, y, z]

    eps : float
        The maximum distance between two samples for one to be considered
        as in the neighborhood of the other.

    min_samples : int
        The number of samples in a neighborhood for a point to be considered
        as a core point.

    metric : str
        The distance metric to use ('euclidean', 'cosine', 'manhattan', 'mahalanobis')

    scale_coords : bool
        Whether to normalize coordinates to balance the 3D aspect ratio.
        Default: True

    x_weight : float
        Weight multiplier for x dimension. Default: 1.0

    y_weight : float
        Weight multiplier for y dimension. Default: 1.0

    z_weight : float
        Weight multiplier for z dimension. Default: 1.0

    measurement_noise_matrix : np.ndarray of shape (3, 3), optional
        Measurement noise covariance matrix for Mahalanobis distance.
        Default: None (uses identity matrix)

    device : str or torch.device, optional
        Device to run computations on

    Returns:
    --------
    labels : numpy array of shape (n_detections,)
        Array with cluster labels (0 for background, 1-n for clusters)
    """
    clusterer = DBSCAN3D(
        eps=eps,
        min_samples=min_samples,
        metric=metric,
        scale_coords=scale_coords,
        x_weight=x_weight,
        y_weight=y_weight,
        z_weight=z_weight,
        measurement_noise_matrix=measurement_noise_matrix,
        device=device,
    )
    return clusterer.fit_predict(detection_coords), clusterer.n_clusters_, clusterer.cluster_centroids_


def dbscan_process(detection_coords, shape):
    # ========== 3D DBSCAN and CENTROIDS CLUSTERING ==========
    if len(detection_coords) > 0:
        # Perform 3D DBSCAN clustering with Mahalanobis distance
        cluster_labels_3d, n_clusters, centroids = dbscan_cluster_3d(
            detection_coords,
            eps=3.0,  # Tune based on your 3D space
            min_samples=10,
            metric="mahalanobis",
            scale_coords=True,
            x_weight=config.SIGMA_RANGE,  # Range weight (512)
            y_weight=config.SIGMA_DOPPLER,  # Doppler weight (64 dimension)
            z_weight=config.SIGMA_AZIMUTH,  # Angle weight (64 smaller dimension)
            measurement_noise_matrix=config.MEASUREMENT_NOISE,
            device="cpu",
        )

        dbscan_data_2d = np.zeros(shape, dtype=np.int32)
        dbscan_angles = np.zeros(shape, dtype=np.float32)

        # Map back to 2D coordinates
        for i, (coord, label) in enumerate(zip(detection_coords, cluster_labels_3d)):
            range_idx = int(coord[0])
            doppler_idx = int(coord[1])
            angle = coord[2]

            # Ensure indices are within bounds
            if 0 <= doppler_idx < shape[0] and 0 <= range_idx < shape[1]:
                dbscan_data_2d[doppler_idx, range_idx] = label
                dbscan_angles[doppler_idx, range_idx] = angle

    else:
        dbscan_data_2d = np.zeros(shape, dtype=np.int32)
        dbscan_angles = np.zeros(shape, dtype=np.float32)
        centroids = {}

    # TODO: remove the zero velocity bins - do this in a more intelligent manner
    dbscan_data_2d[32, :] = 0
    dbscan_angles[32, :] = 0

    return dbscan_data_2d, dbscan_angles, centroids


# more efficient to compute centroids along with dbscan clustering
def centroid_process(centroids, shape):
    # CENTROIDS ==============

    # Create centroids map for plotting
    centroids_map = np.zeros(shape, dtype=np.int32)
    centroids_angles = np.zeros(shape, dtype=np.float32)

    if len(centroids) > 0:
        cluster_labels, centroid_data = zip(*centroids.items())

        large_cluster_mask = np.array([c[1] for c in centroid_data]) > 0
        large_cluster_idx = np.where(large_cluster_mask)[0]
        filtered_centroids = tuple(centroid_data[i] for i in large_cluster_idx)
        cluster_labels = tuple(cluster_labels[i] for i in large_cluster_idx)

        centroids_3d = [centroid[0] for centroid in filtered_centroids]
        centroids_tensor = torch.stack(centroids_3d)

        # Round only the first two dimensions (range and doppler)
        centroids_rounded = torch.stack(
            [
                torch.round(centroids_tensor[:, 0]),
                torch.round(centroids_tensor[:, 1]),
                centroids_tensor[:, 2],  # Keep angle as float
            ]
        ).T

        # Clip each dimension to its respective range
        centroids_clipped = torch.stack(
            [
                torch.clamp(centroids_rounded[:, 0], 0, shape[0] - 1),
                torch.clamp(centroids_rounded[:, 1], 0, shape[1] - 1),
                centroids_rounded[:, 2],  # Angle not clipped
            ]
        ).T

        # Convert to numpy
        centroids_3d_for_indexing = centroids_clipped[:, :2].cpu().numpy().astype(int)
        centroids_3d_angles_rad = centroids_clipped[:, 2].cpu().numpy().astype(np.float32)
        centroids_3d_angles = np.rad2deg(centroids_3d_angles_rad)
        
        # Assign cluster labels to maps
        for label_idx, (range_idx, doppler_idx) in enumerate(centroids_3d_for_indexing):
            centroids_map[doppler_idx, range_idx] = cluster_labels[label_idx]
            centroids_angles[doppler_idx, range_idx] = centroids_3d_angles[label_idx]

    centroids_map[32, :] = 0
    centroids_angles[32, :] = 0

    return centroids_map, centroids_angles


# Legacy support for 2D DBSCAN if needed
class DBSCAN:
    """
    2D DBSCAN clustering algorithm implemented in PyTorch for GPU acceleration.
    """

    def __init__(
        self,
        eps: float = 0.5,
        min_samples: int = 5,
        metric: str = "euclidean",
        scale_coords: bool = True,
        row_weight: float = 1.0,
        col_weight: float = 0.25,
        device: Optional[str] = None,
    ):
        self.eps = eps
        self.min_samples = min_samples
        self.metric = metric
        self.scale_coords = scale_coords
        self.row_weight = row_weight
        self.col_weight = col_weight

        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)

        self.labels_ = None
        self.core_sample_indices_ = None
        self.n_clusters_ = 0

    def _compute_distance_matrix(self, X: torch.Tensor) -> torch.Tensor:
        if self.metric == "euclidean":
            norms = (X**2).sum(dim=1, keepdim=True)
            distances = norms + norms.T - 2 * torch.mm(X, X.T)
            distances = torch.sqrt(torch.clamp(distances, min=0))
        elif self.metric == "cosine":
            X_normalized = F.normalize(X, p=2, dim=1)
            cosine_sim = torch.mm(X_normalized, X_normalized.T)
            distances = 1 - cosine_sim
        elif self.metric == "manhattan":
            distances = torch.cdist(X, X, p=1)
        else:
            raise ValueError(f"Unsupported metric: {self.metric}")
        return distances

    def fit(self, detection_coords: torch.Tensor) -> "DBSCAN":
        if not isinstance(detection_coords, torch.Tensor):
            detection_coords = torch.tensor(detection_coords, dtype=torch.float32)

        detection_coords = detection_coords.to(self.device).clone()
        n_samples = detection_coords.shape[0]

        if self.scale_coords:
            scaled_coords = detection_coords.clone()
            scaled_coords[:, 0] = scaled_coords[:, 0] * self.row_weight
            scaled_coords[:, 1] = scaled_coords[:, 1] * self.col_weight
        else:
            scaled_coords = detection_coords

        distances = self._compute_distance_matrix(scaled_coords)
        neighbors_mask = distances <= self.eps
        neighbor_counts = neighbors_mask.sum(dim=1)
        is_core = neighbor_counts >= self.min_samples
        self.core_sample_indices_ = torch.where(is_core)[0]

        labels = torch.full((n_samples,), -1, dtype=torch.long, device=self.device)
        current_cluster = 1
        visited = torch.zeros(n_samples, dtype=torch.bool, device=self.device)

        for idx in range(n_samples):
            if visited[idx] or not is_core[idx]:
                continue
            visited[idx] = True
            labels[idx] = current_cluster
            seeds = torch.where(neighbors_mask[idx])[0].tolist()
            seed_set = set(seeds)
            while seed_set:
                current_point = seed_set.pop()
                if visited[current_point]:
                    continue
                visited[current_point] = True
                labels[current_point] = current_cluster
                if is_core[current_point]:
                    new_neighbors = torch.where(neighbors_mask[current_point])[0]
                    for neighbor in new_neighbors:
                        neighbor_idx = neighbor.item()
                        if not visited[neighbor_idx]:
                            seed_set.add(neighbor_idx)
            current_cluster += 1
        self.labels_ = labels
        self.n_clusters_ = current_cluster
        return self

    def fit_predict(self, detection_array: np.ndarray) -> np.ndarray:
        if detection_array.ndim != 2:
            raise ValueError(f"Expected 2D array, got {detection_array.ndim}D")
        shape = detection_array.shape
        cluster_output = np.zeros(shape, dtype=np.int32)
        detection_coords = np.argwhere(detection_array == 1)
        if len(detection_coords) == 0:
            return cluster_output
        self.fit(detection_coords)
        labels_cpu = self.labels_.cpu().numpy()
        for i, coord in enumerate(detection_coords):
            if labels_cpu[i] != -1:
                cluster_output[coord[0], coord[1]] = labels_cpu[i]
        noise_cluster_id = self.n_clusters_ + 1
        for i, coord in enumerate(detection_coords):
            if labels_cpu[i] == -1:
                cluster_output[coord[0], coord[1]] = noise_cluster_id
                noise_cluster_id += 1
        return cluster_output


def dbscan_cluster(
    detection_array: np.ndarray,
    eps: float = 0.5,
    min_samples: int = 5,
    metric: str = "euclidean",
    scale_coords: bool = True,
    row_weight: float = 1.0,
    col_weight: float = 0.25,
    device: Optional[str] = None,
) -> np.ndarray:
    clusterer = DBSCAN(
        eps=eps,
        min_samples=min_samples,
        metric=metric,
        scale_coords=scale_coords,
        row_weight=row_weight,
        col_weight=col_weight,
        device=device,
    )
    return clusterer.fit_predict(detection_array)


if __name__ == "__main__":
    # Sample 3D test
    print("Testing 3D DBSCAN...")
    coords = np.array([[10, 20, 5], [10.1, 20.1, 5.1], [50, 60, 30]])
    labels, n, centroids = dbscan_cluster_3d(coords, eps=1.0, min_samples=2)
    print(f"Labels: {labels}")
    print(f"Clusters: {n}")
    print(f"Centroids count: {len(centroids)}")
