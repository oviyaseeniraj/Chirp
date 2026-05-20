"""PyTorch-based 3D DBSCAN clustering."""

from typing import Optional, Tuple
import numpy as np
import torch
import torch.nn.functional as F

from .. import config


class DBSCAN3D:
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
        self.eps_sq = eps * eps
        self.min_samples = min_samples
        self.metric = metric
        self.scale_coords = scale_coords
        self.x_weight = x_weight
        self.y_weight = y_weight
        self.z_weight = z_weight

        self.device = torch.device(device) if device else torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )

        if measurement_noise_matrix is None:
            self.measurement_noise_matrix = torch.eye(3, device=self.device)
        else:
            if isinstance(measurement_noise_matrix, np.ndarray):
                measurement_noise_matrix = torch.from_numpy(measurement_noise_matrix)
            self.measurement_noise_matrix = measurement_noise_matrix.float().to(self.device)

        self.measurement_noise_matrix_inv = torch.linalg.inv(self.measurement_noise_matrix)

        self.labels_ = None
        self.core_sample_indices_ = None
        self.n_clusters_ = 0
        self.cluster_centroids_ = {}

    def _compute_distance_matrix(self, X: torch.Tensor) -> torch.Tensor:
        if self.metric == "euclidean":
            norms = (X**2).sum(dim=1, keepdim=True)
            distances_sq = norms + norms.T - 2 * torch.mm(X, X.T)
            return torch.sqrt(torch.clamp(distances_sq, min=0))

        if self.metric == "cosine":
            X_normalized = F.normalize(X, p=2, dim=1)
            cosine_sim = torch.mm(X_normalized, X_normalized.T)
            return 1 - cosine_sim

        if self.metric == "manhattan":
            return torch.cdist(X, X, p=1)

        if self.metric == "mahalanobis":
            diff = X.unsqueeze(1) - X.unsqueeze(0)
            mahal_inner = torch.einsum("ijk,kl->ijl", diff, self.measurement_noise_matrix_inv)
            mahal_sq = torch.sum(diff * mahal_inner, dim=2)
            return torch.sqrt(torch.clamp(mahal_sq, min=0))

        raise ValueError(f"Unsupported metric: {self.metric}")

    def _get_neighbors_mask(self, distances: torch.Tensor) -> torch.Tensor:
        return distances <= self.eps

    def _weighted_median(self, values: torch.Tensor, weights: torch.Tensor) -> torch.Tensor:
        sorted_idx = torch.argsort(values)
        values_sorted = values[sorted_idx]
        weights_sorted = weights[sorted_idx]

        cum_weights = torch.cumsum(weights_sorted, dim=0)
        cutoff = 0.5 * torch.sum(weights_sorted)

        median_idx = torch.searchsorted(cum_weights, cutoff)
        median_idx = torch.clamp(median_idx, 0, len(values_sorted) - 1)

        return values_sorted[median_idx]

    def fit(
        self,
        detection_coords: torch.Tensor,
        detection_power=None,
        power_threshold: float = 0.0,
    ) -> "DBSCAN3D":
        if not isinstance(detection_coords, torch.Tensor):
            detection_coords = torch.tensor(detection_coords, dtype=torch.float32)

        detection_coords = detection_coords.to(self.device).clone()

        # Input expected here:
        # detection_coords[:, 0] = range in meters
        # detection_coords[:, 1] = Doppler velocity in m/s
        # detection_coords[:, 2] = azimuth in degrees
        #
        # Internally, azimuth is converted to spatial frequency:
        # u = pi * sin(theta)
        # Therefore, for Mahalanobis DBSCAN, MEASUREMENT_NOISE[2, 2]
        # should be the variance of this spatial-frequency coordinate.
        detection_coords[:, 2] = torch.deg2rad(detection_coords[:, 2])
        original_angles = detection_coords[:, 2].clone()
        detection_coords[:, 2] = np.pi * torch.sin(original_angles)

        n_samples = detection_coords.shape[0]

        if n_samples == 0:
            self.labels_ = torch.tensor([], dtype=torch.long, device=self.device)
            self.n_clusters_ = 0
            self.cluster_centroids_ = {}
            return self

        if detection_power is not None:
            if not isinstance(detection_power, torch.Tensor):
                detection_power = torch.tensor(detection_power, dtype=torch.float32)
            detection_power = detection_power.to(self.device).float()
        else:
            detection_power = torch.ones(n_samples, device=self.device)

        # detection_power is expected to be MATLAB-style dB power:
        # 10 * log10(linear_power + eps)
        detection_power = torch.nan_to_num(
            detection_power,
            nan=0.0,
            neginf=0.0,
            posinf=120.0,
        )

        if self.metric == "mahalanobis":
            # Mahalanobis already applies covariance-based coordinate scaling.
            # Do not also apply x_weight/y_weight/z_weight here.
            scaled_coords = detection_coords
        elif self.scale_coords:
            scaled_coords = detection_coords.clone()
            scaled_coords[:, 0] *= self.x_weight
            scaled_coords[:, 1] *= self.y_weight
            scaled_coords[:, 2] *= self.z_weight
        else:
            scaled_coords = detection_coords

        distances = self._compute_distance_matrix(scaled_coords)
        neighbors_mask = self._get_neighbors_mask(distances)

        neighbor_counts = neighbors_mask.sum(dim=1)
        is_core = neighbor_counts >= self.min_samples
        core_indices = torch.where(is_core)[0]

        self.core_sample_indices_ = core_indices

        labels = torch.full((n_samples,), -1, dtype=torch.long, device=self.device)
        visited = torch.zeros(n_samples, dtype=torch.bool, device=self.device)

        current_cluster = 1

        for core_idx in core_indices:
            core_idx_int = core_idx.item()

            if visited[core_idx_int] or labels[core_idx_int] != -1:
                continue

            visited[core_idx_int] = True
            labels[core_idx_int] = current_cluster

            neighbor_indices = torch.where(neighbors_mask[core_idx_int])[0]
            seeds = set(neighbor_indices.cpu().numpy())

            while seeds:
                current_point = seeds.pop()

                if visited[current_point]:
                    continue

                visited[current_point] = True

                if labels[current_point] == -1:
                    labels[current_point] = current_cluster

                if is_core[current_point]:
                    new_neighbors = torch.where(neighbors_mask[current_point])[0]
                    new_seeds = set(new_neighbors.cpu().numpy())
                    visited_indices = set(visited.cpu().numpy().nonzero()[0])
                    seeds.update(new_seeds - visited_indices)

            current_cluster += 1

        self.cluster_centroids_ = {}

        temp = []

        for cluster_id in range(1, current_cluster):
            cluster_mask = labels == cluster_id
            # print("cluster_mask: ", cluster_mask)
            cluster_points = detection_coords[cluster_mask]

            if len(cluster_points) == 0:
                continue

            # dB power values from rdm_power_db
            cluster_power_db = detection_power[cluster_mask]

            # Use linear power only for max-power thresholding
            cluster_power_linear = torch.pow(10.0, cluster_power_db / 10.0)
            cluster_max_power = torch.max(cluster_power_linear)
            cluster_max_power_db = torch.max(cluster_power_db)


            if cluster_max_power_db < power_threshold:
                labels[cluster_mask] = -1
                continue

            # print("labels[cluster_mask]: ", labels[cluster_mask])

            # Use dB power directly for centroid weighting
            cluster_power = cluster_power_db

            if torch.sum(cluster_power) <= 0:
                cluster_power = torch.ones_like(cluster_power)

            w = cluster_power / torch.sum(cluster_power)

            # Physical range centroid: power-weighted mean, meters.
            range_centroid = torch.sum(w * cluster_points[:, 0])

            # Physical Doppler centroid: power-weighted median, m/s.
            doppler_centroid = self._weighted_median(cluster_points[:, 1], cluster_power)

            # Azimuth centroid: power-weighted mean in spatial-frequency domain,
            # converted back to angle radians.
            frequencies = cluster_points[:, 2]
            weighted_freq = torch.sum(w * frequencies)
            angle_centroid = torch.arcsin(torch.clamp(weighted_freq / np.pi, -1.0, 1.0))

            if abs(doppler_centroid.item()) > 0:  # Example threshold, adjust as needed
                self.cluster_centroids_[cluster_id] = (
                    torch.tensor(
                        [
                            range_centroid.item(),
                            doppler_centroid.item(),
                            angle_centroid.item(),
                        ],
                        device=self.device,
                    ),
                    len(cluster_points),
                )   
    
                # print("labels[cluster_id]: ", labels[cluster_id])
                if labels[cluster_mask][0].item() != -1:
                    temp.append((cluster_id, range_centroid.item(), doppler_centroid.item(), angle_centroid.item(), cluster_max_power_db.item(), len(cluster_points)))
        self.labels_ = labels

        # Count only clusters that survived power-threshold filtering.
        # Labels may have gaps because rejected clusters are set back to -1.
        self.n_clusters_ = len(self.cluster_centroids_)
        if self.n_clusters_ > 1:
            for thing in temp:
                print("cluster_id: {}, range_centroid: {:.2f} m, doppler_centroid: {:.2f} m/s, angle_centroid: {:.2f} deg, max_power_db: {:.2f} dB, num_points: {}".format(
                    thing[0], thing[1], thing[2], np.rad2deg(thing[3]), thing[4], thing[5]
                ))
        return self

    def fit_predict(
        self,
        detection_coords: np.ndarray,
        detection_power=None,
        power_threshold: float = 0.0,
    ) -> np.ndarray:
        if len(detection_coords) == 0:
            return np.array([], dtype=np.int32)

        if detection_coords.ndim != 2 or detection_coords.shape[1] != 3:
            raise ValueError(f"Expected shape (n_detections, 3), got {detection_coords.shape}")

        self.fit(detection_coords, detection_power, power_threshold)

        labels_cpu = self.labels_.cpu().numpy()
        output_labels = labels_cpu.copy()

        valid_labels = labels_cpu[labels_cpu != -1]
        noise_cluster_id = int(valid_labels.max()) + 1 if len(valid_labels) > 0 else 1

        # Give each noise point a unique positive label for visualization,
        # without colliding with any surviving cluster label.
        for i in range(len(labels_cpu)):
            if labels_cpu[i] == -1:
                output_labels[i] = noise_cluster_id
                noise_cluster_id += 1

        return output_labels.astype(np.int32)


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
    detection_power=None,
    power_threshold: float = 0.0,
) -> Tuple[np.ndarray, int, dict]:
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

    labels = clusterer.fit_predict(
        detection_coords,
        detection_power=detection_power,
        power_threshold=power_threshold,
    )

    return labels, clusterer.n_clusters_, clusterer.cluster_centroids_


def dbscan_process(detection_coords, shape, detection_power=None):
    if len(detection_coords) > 0:
        cluster_labels_3d, n_clusters, centroids = dbscan_cluster_3d(
            detection_coords,
            eps=3.0,
            min_samples=15,
            metric="mahalanobis",
            scale_coords=True,
            x_weight=config.SIGMA_RANGE,
            y_weight=config.SIGMA_DOPPLER,
            z_weight=config.SIGMA_AZIMUTH,
            measurement_noise_matrix=config.MEASUREMENT_NOISE,
            device="cpu",
            detection_power=detection_power,
            power_threshold=getattr(config, "CLUSTER_MAX_POWER_THRESHOLD", 100),
        )
        

        dbscan_data_2d = np.zeros(shape, dtype=np.int32)
        dbscan_angles = np.zeros(shape, dtype=np.float32)

        for coord, label in zip(detection_coords, cluster_labels_3d):
            range_idx = int(round(coord[0] / config.RANGE_RES))
            doppler_idx = int(
                round((coord[1] / config.DOPPLER_RES) + (config.DOPPLER_BINS / 2.0))
            )
            angle = coord[2]

            if 0 <= doppler_idx < shape[0] and 0 <= range_idx < shape[1]:
                dbscan_data_2d[doppler_idx, range_idx] = label
                dbscan_angles[doppler_idx, range_idx] = angle
    else:
        dbscan_data_2d = np.zeros(shape, dtype=np.int32)
        dbscan_angles = np.zeros(shape, dtype=np.float32)
        centroids = {}

    zero_doppler_idx = config.DOPPLER_BINS // 2
    dbscan_data_2d[zero_doppler_idx, :] = 0
    dbscan_angles[zero_doppler_idx, :] = 0

    return dbscan_data_2d, dbscan_angles, centroids


def centroid_process(centroids, shape):
    centroids_map = np.zeros(shape, dtype=np.int32)
    centroids_angles = np.zeros(shape, dtype=np.float32)

    if len(centroids) > 0:
        cluster_labels, centroid_data = zip(*centroids.items())

        large_cluster_mask = np.array([c[1] for c in centroid_data]) > 0
        large_cluster_idx = np.where(large_cluster_mask)[0]

        filtered_centroids = tuple(centroid_data[i] for i in large_cluster_idx)
        cluster_labels = tuple(cluster_labels[i] for i in large_cluster_idx)

        for label_idx, centroid in enumerate(filtered_centroids):
            centroid_vec = centroid[0].cpu().numpy()

            range_m = float(centroid_vec[0])
            doppler_mps = float(centroid_vec[1])
            angle_rad = float(centroid_vec[2])

            range_idx = int(round(range_m / config.RANGE_RES))
            doppler_idx = int(
                round((doppler_mps / config.DOPPLER_RES) + (config.DOPPLER_BINS / 2.0))
            )

            if 0 <= doppler_idx < shape[0] and 0 <= range_idx < shape[1]:
                centroids_map[doppler_idx, range_idx] = cluster_labels[label_idx]
                centroids_angles[doppler_idx, range_idx] = np.rad2deg(angle_rad)

    zero_doppler_idx = config.DOPPLER_BINS // 2
    centroids_map[zero_doppler_idx, :] = 0
    centroids_angles[zero_doppler_idx, :] = 0

    return centroids_map, centroids_angles
