# Rolling K-Means Clustering for Sparse Detection Data

from collections import deque

import numpy as np
from sklearn.cluster import MiniBatchKMeans


class RollingKMeans:
    """
    Rolling K-Means clustering for sparse detection data.
    Processes 64x256 numpy arrays where detections are marked as 1 and background as 0.
    """

    def __init__(self, n_clusters=5, window_size=10, min_detections=3):
        """
        Initialize Rolling K-Means clustering.

        Args:
            n_clusters: Number of clusters to form
            window_size: Number of frames to keep in rolling window
            min_detections: Minimum number of detections needed to perform clustering
        """
        self.n_clusters = n_clusters
        self.window_size = window_size
        self.min_detections = min_detections
        self.detection_buffer = deque(maxlen=window_size)
        self.kmeans = MiniBatchKMeans(n_clusters=n_clusters, random_state=42, n_init=3)
        self.is_fitted = False

    def fit_predict(self, detection_array):
        """
        Fit the rolling k-means model and predict cluster labels.

        Args:
            detection_array: numpy array of shape (64, 256) with 1s for detections, 0s for background

        Returns:
            numpy array of shape (64, 256) with cluster labels (0 to n_clusters-1, -1 for background)
        """
        if detection_array.shape != (64, 256):
            raise ValueError(f"Expected shape (64, 256), got {detection_array.shape}")

        # Initialize output array with -1 (background label)
        cluster_output = np.full((64, 256), -1, dtype=np.int32)

        # Extract detection coordinates
        detection_coords = np.argwhere(detection_array == 1)

        if len(detection_coords) == 0:
            return cluster_output

        # Add current detections to buffer
        self.detection_buffer.append(detection_coords)

        # Combine all detections in the rolling window
        all_detections = np.vstack(list(self.detection_buffer))

        # Only cluster if we have enough detections
        if len(all_detections) < self.min_detections:
            # Not enough data, assign all current detections to cluster 0
            for coord in detection_coords:
                cluster_output[coord[0], coord[1]] = 0
            return cluster_output

        # Fit or update the k-means model
        if not self.is_fitted or len(all_detections) >= self.min_detections * 2:
            self.kmeans.partial_fit(all_detections)
            self.is_fitted = True

        # Predict clusters for current frame's detections
        if len(detection_coords) > 0:
            cluster_labels = self.kmeans.predict(detection_coords)

            # Assign cluster labels to output array
            for i, coord in enumerate(detection_coords):
                cluster_output[coord[0], coord[1]] = cluster_labels[i]

        return cluster_output

    def reset(self):
        """Reset the rolling window and model state."""
        self.detection_buffer.clear()
        self.is_fitted = False
        self.kmeans = MiniBatchKMeans(
            n_clusters=self.n_clusters, random_state=42, n_init=3
        )


def rolling_kmeans_cluster(detection_array, n_clusters=5):
    """
    Convenience function for single-frame clustering without rolling window.

    Args:
        detection_array: numpy array of shape (64, 256) with 1s for detections, 0s for background
        n_clusters: Number of clusters to form

    Returns:
        numpy array of shape (64, 256) with cluster labels (0 to n_clusters-1, -1 for background)
    """
    if detection_array.shape != (64, 256):
        raise ValueError(f"Expected shape (64, 256), got {detection_array.shape}")

    # Initialize output array with -1 (background label)
    cluster_output = np.full((64, 256), -1, dtype=np.int32)

    # Extract detection coordinates
    detection_coords = np.argwhere(detection_array == 1)

    if len(detection_coords) < n_clusters:
        # Not enough detections for clustering, assign sequential labels
        for i, coord in enumerate(detection_coords):
            cluster_output[coord[0], coord[1]] = min(i, n_clusters - 1)
        return cluster_output

    # Perform k-means clustering
    kmeans = MiniBatchKMeans(n_clusters=n_clusters, random_state=42, n_init=3)
    cluster_labels = kmeans.fit_predict(detection_coords)

    # Assign cluster labels to output array
    for i, coord in enumerate(detection_coords):
        cluster_output[coord[0], coord[1]] = cluster_labels[i]

    return cluster_output


# Example usage
if __name__ == "__main__":
    # Create sample detection array
    test_array = np.zeros((64, 256))

    # Add some detections in different regions
    test_array[10:15, 20:25] = 1  # Cluster 1
    test_array[30:35, 100:105] = 1  # Cluster 2
    test_array[50:52, 200:203] = 1  # Cluster 3

    # Single-frame clustering
    print("Single-frame clustering:")
    result = rolling_kmeans_cluster(test_array, n_clusters=3)
    print(f"Unique cluster labels: {np.unique(result)}")
    print(f"Number of detections per cluster:")
    for label in np.unique(result):
        if label != -1:
            count = np.sum(result == label)
            print(f"  Cluster {label}: {count} pixels")

    # Rolling window clustering
    print("\nRolling window clustering:")
    rolling_km = RollingKMeans(n_clusters=3, window_size=5)

    # Process multiple frames
    for frame_idx in range(3):
        # Create varying detection patterns
        frame = np.zeros((64, 256))
        offset = frame_idx * 5
        frame[10 + offset : 15 + offset, 20:25] = 1
        frame[30:35, 100 + offset : 105 + offset] = 1

        result = rolling_km.fit_predict(frame)
        print(
            f"Frame {frame_idx}: {np.sum(frame == 1)} detections, "
            f"{len(np.unique(result)) - 1} clusters"
        )
