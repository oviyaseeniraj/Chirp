"""
PyTorch-based DBSCAN (Density-Based Spatial Clustering of Applications with Noise)
Implementation optimized for GPU acceleration with exposed critical parameters.

Input: 64 * 512 detection array (1s for detections, 0s for background)
Output: 64 * 512 array with cluster labels (0 for background, 1-n for clusters)
"""

from typing import Optional, Tuple

import numpy as np
import torch
import torch.nn.functional as F

class DBSCAN:
    """
    DBSCAN clustering algorithm implemented in PyTorch for GPU acceleration.

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
        The distance metric to use. Options: 'euclidean', 'cosine', 'manhattan'
        Default: 'euclidean'

    scale_coords : bool
        Whether to normalize coordinates to balance the 64x512 aspect ratio.
        When True, coordinates are scaled so distances are balanced across dimensions.
        Default: True

    row_weight : float
        Weight multiplier for row dimension (64). Use this to adjust relative importance
        of vertical vs horizontal distances. Higher values make vertical distances more important.
        Only used when scale_coords=True.
        Default: 1.0

    col_weight : float
        Weight multiplier for column dimension (512). Use this to adjust relative importance
        of horizontal vs vertical distances. Higher values make horizontal distances more important.
        Only used when scale_coords=True.
        Default: 0.25 (compensates for 4x wider dimension)

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
        """
        Compute pairwise distance matrix based on the specified metric.

        Parameters:
        -----------
        X : torch.Tensor of shape (n_samples, n_features)
            Input data

        Returns:
        --------
        distances : torch.Tensor of shape (n_samples, n_samples)
            Pairwise distance matrix
        """
        if self.metric == "euclidean":
            # Efficient euclidean distance computation: ||a - b||^2 = ||a||^2 + ||b||^2 - 2<a,b>
            norms = (X**2).sum(dim=1, keepdim=True)
            distances = norms + norms.T - 2 * torch.mm(X, X.T)
            distances = torch.sqrt(torch.clamp(distances, min=0))

        elif self.metric == "cosine":
            # Cosine distance = 1 - cosine similarity
            X_normalized = F.normalize(X, p=2, dim=1)
            cosine_sim = torch.mm(X_normalized, X_normalized.T)
            distances = 1 - cosine_sim

        elif self.metric == "manhattan":
            # Manhattan distance (L1 norm)
            distances = torch.cdist(X, X, p=1)

        elif self.metric == "mahalanobis":
            #need a measurement
            distances = torch.

        else:
            raise ValueError(f"Unsupported metric: {self.metric}")

        return distances

    def _get_neighbors(self, distances: torch.Tensor) -> torch.Tensor:
        """
        Find neighbors within eps distance for each point.

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

    def fit(self, detection_coords: torch.Tensor) -> "DBSCAN":
        """
        Perform DBSCAN clustering on detection coordinates.

        Parameters:
        -----------
        detection_coords : torch.Tensor of shape (n_detections, 2)
            Detection coordinates [row, col]

        Returns:
        --------
        self : DBSCAN
            Fitted estimator
        """
        if not isinstance(detection_coords, torch.Tensor):
            detection_coords = torch.tensor(detection_coords, dtype=torch.float32)

        detection_coords = detection_coords.to(self.device)
        n_samples = detection_coords.shape[0]

        # Scale coordinates to balance aspect ratio if enabled
        if self.scale_coords:
            scaled_coords = detection_coords.clone()
            scaled_coords[:, 0] = scaled_coords[:, 0] * self.row_weight
            scaled_coords[:, 1] = scaled_coords[:, 1] * self.col_weight
        else:
            scaled_coords = detection_coords

        # Compute distance matrix
        distances = self._compute_distance_matrix(scaled_coords)

        # Find neighbors for each point
        neighbors_mask = self._get_neighbors(distances)
        neighbor_counts = neighbors_mask.sum(dim=1)

        # Identify core points (points with at least min_samples neighbors)
        is_core = neighbor_counts >= self.min_samples
        self.core_sample_indices_ = torch.where(is_core)[0]

        # Initialize labels (-1 means noise/unassigned internally)
        labels = torch.full((n_samples,), -1, dtype=torch.long, device=self.device)

        current_cluster = 1  # Start from 1 (0 reserved for background)
        visited = torch.zeros(n_samples, dtype=torch.bool, device=self.device)

        # Process each core point
        for idx in range(n_samples):
            if visited[idx] or not is_core[idx]:
                continue

            # Start a new cluster
            visited[idx] = True
            labels[idx] = current_cluster

            # Find all density-reachable points (breadth-first search)
            seeds = torch.where(neighbors_mask[idx])[0].tolist()
            seed_set = set(seeds)

            while seed_set:
                current_point = seed_set.pop()

                if visited[current_point]:
                    continue

                visited[current_point] = True
                labels[current_point] = current_cluster

                # If current point is a core point, add its neighbors to seeds
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
        """
        Fit the DBSCAN model and predict cluster labels.

        Parameters:
        -----------
        detection_array : numpy array of shape (64, 512)
            Detection array with 1s for detections, 0s for background

        Returns:
        --------
        cluster_output : numpy array of shape (64, 512)
            Array with cluster labels (0 for background, 1-n for clusters)
        """
        if detection_array.shape != (64, 512):
            raise ValueError(f"Expected shape (64, 512), got {detection_array.shape}")

        # Initialize output array with 0 (background label)
        cluster_output = np.full((64, 512), 0, dtype=np.int32)

        # Extract detection coordinates
        detection_coords = np.argwhere(detection_array == 1)

        if len(detection_coords) == 0:
            return cluster_output

        # Perform DBSCAN clustering on coordinates
        self.fit(detection_coords)

        # Assign cluster labels to output array at detection positions
        # Map internal labels: -1 (noise) -> sequential IDs after main clusters
        labels_cpu = self.labels_.cpu().numpy()

        # First, assign main cluster labels (already start from 1)
        for i, coord in enumerate(detection_coords):
            if labels_cpu[i] != -1:
                cluster_output[coord[0], coord[1]] = labels_cpu[i]

        # Then assign noise points to individual clusters
        noise_cluster_id = self.n_clusters_ + 1
        for i, coord in enumerate(detection_coords):
            if labels_cpu[i] == -1:
                cluster_output[coord[0], coord[1]] = noise_cluster_id
                noise_cluster_id += 1

        return cluster_output

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

        for cluster_id in range(self.n_clusters_):
            size = (self.labels_ == cluster_id).sum().item()
            cluster_sizes.append(size)

        return {
            "n_clusters": self.n_clusters_,
            "n_noise_points": n_noise,
            "cluster_sizes": cluster_sizes,
            "n_core_points": len(self.core_sample_indices_),
            "eps": self.eps,
            "min_samples": self.min_samples,
            "metric": self.metric,
            "scale_coords": self.scale_coords,
            "row_weight": self.row_weight,
            "col_weight": self.col_weight,
        }


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
    """
    Convenience function to perform DBSCAN clustering on detection array.

    Parameters:
    -----------
    detection_array : numpy array of shape (64, 512)
        Detection array with 1s for detections, 0s for background

    eps : float
        The maximum distance between two samples for one to be considered
        as in the neighborhood of the other.

    min_samples : int
        The number of samples in a neighborhood for a point to be considered
        as a core point.

    metric : str
        The distance metric to use ('euclidean', 'cosine', 'manhattan')

    scale_coords : bool
        Whether to normalize coordinates to balance the 64x512 aspect ratio.
        Default: True

    row_weight : float
        Weight multiplier for row dimension (64). Default: 1.0

    col_weight : float
        Weight multiplier for column dimension (512). Default: 0.25

    device : str or torch.device, optional
        Device to run computations on

    Returns:
    --------
    cluster_output : numpy array of shape (64, 512)
        Array with cluster labels (0 for background, 1-n for clusters)

    Example:
    --------
    >>> detection_array = np.zeros((64, 512))
    >>> detection_array[10:15, 20:25] = 1  # Add some detections
    >>> result = dbscan_cluster(detection_array, eps=5.0, min_samples=3)
    >>> print(f"Unique labels: {np.unique(result)}")
    """
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


# Example usage
if __name__ == "__main__":
    # Create sample detection array
    test_array = np.zeros((64, 512))

    # Add some detections in different regions
    test_array[10:15, 20:25] = 1  # Region 1
    test_array[30:35, 100:105] = 1  # Region 2
    test_array[50:52, 200:203] = 1  # Region 3
    test_array[12, 102] = 1  # Potential noise point

    print("Running DBSCAN on 64x512 detection array...")
    print(f"Device: {'cuda' if torch.cuda.is_available() else 'cpu'}")
    print(f"Total detections: {np.sum(test_array == 1)}")

    # Method 1: Using the class with coordinate scaling
    # eps can be smaller now since coordinates are normalized
    dbscan_model = DBSCAN(eps=3.0, min_samples=3, metric="euclidean", scale_coords=True)
    result = dbscan_model.fit_predict(test_array)

    print("\nClustering Results:")
    info = dbscan_model.get_cluster_info()
    for key, value in info.items():
        print(f"  {key}: {value}")

    # Method 2: Using the convenience function
    result2 = dbscan_cluster(test_array, eps=3.0, min_samples=3, scale_coords=True)
    print(f"\nUnique cluster labels: {np.unique(result2)}")

    # Method 3: Custom weights for anisotropic clustering
    # If you want to prioritize row clustering over column clustering
    result3 = dbscan_cluster(
        test_array, eps=3.0, min_samples=3, row_weight=2.0, col_weight=0.5
    )
    print(f"Custom weights unique labels: {np.unique(result3)}")

    # Show label distribution
    print("\nLabel distribution:")
    for label in np.unique(result):
        if label == 0:
            print(f"  Background: {np.sum(result == 0)} pixels")
        else:
            count = np.sum(result == label)
            if count == 1:
                print(f"  Noise point (Cluster {label}): {count} pixel")
            else:
                print(f"  Cluster {label}: {count} pixels")
