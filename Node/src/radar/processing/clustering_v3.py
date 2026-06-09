"""PyTorch-based 3D DBSCAN clustering with sklearn-accelerated execution.

Performance Strategy
--------------------
Three layers of optimization, from most impactful to least:

1. **sklearn DBSCAN** (replaces custom BFS + distance matrix)
   - Uses tree-based neighbor search (Ball Tree / KD Tree): O(N log N) vs O(N²)
   - BFS expansion runs in Cython (compiled C), not Python sets
   - Supports Mahalanobis distance natively with ``metric_params``

2. **GPU centroid computation** (for power-weighted centroids)
   - Cluster labels from sklearn are transferred back to GPU
   - Power-threshold filtering and weighted centroid calc remain vectorized on GPU

3. **Hybrid GPU-CPU data flow**
   - Coordinate transformation (azimuth → spatial frequency) on GPU
   - sklearn clustering on CPU (inevitable — sklearn is CPU-only)
   - Centroid computation on GPU
"""

import time
from typing import Optional, Tuple

import numpy as np
import torch
import torch.nn.functional as F

from .. import config

# ---------------------------------------------------------------------------
# Profiling / debug level
# ---------------------------------------------------------------------------
#   0  =  silent
#   1  =  summary every PRINT_INTERVAL cycles
#   2  =  per-cycle detailed  (includes sub-steps)
DEBUG_LEVEL = 1
PRINT_INTERVAL = 50  # only matters when DEBUG_LEVEL == 1

# Running timer stats:  {name: (total_seconds, call_count, current_delta)}
_timer_stats: dict = {}
_timers: dict = {}


def _start_timer(name: str) -> None:
    _timers[name] = time.perf_counter()


def _stop_timer(name: str, level: int = 1) -> float:
    """Stop *name* and accumulate stats.  Returns the current delta."""
    t0 = _timers.pop(name, None)
    if t0 is None:
        return 0.0
    dt = time.perf_counter() - t0
    total, count, _ = _timer_stats.get(name, (0.0, 0, 0.0))
    total += dt
    count += 1
    _timer_stats[name] = (total, count, dt)
    if DEBUG_LEVEL >= level:
        avg_us = (total / count) * 1e6
        cur_us = dt * 1e6
        print(
            f"    [{name:>16s}]  {cur_us:8.0f} us  (avg {avg_us:7.0f} us,  n={count})"
        )
    return dt


def _print_cycle_summary(fit_tag: str) -> None:
    """Print a single-line per-cycle summary matching the user's format."""
    if DEBUG_LEVEL < 1:
        return
    total_s, total_n, total_cur = _timer_stats.get(fit_tag, (0.0, 0, 0.0))
    if total_n < 1:
        return
    # level 1 → throttle; level 2 → print every cycle
    if DEBUG_LEVEL == 1 and (total_n % PRINT_INTERVAL) != 0:
        return
    avg_ms = (total_s / total_n) * 1000.0
    tot_us = total_cur * 1e6
    # ── pull current deltas for sub-steps  ────────────────────────
    _, _, clus = _timer_stats.get("cluster", (0.0, 0, 0.0))
    _, _, cent = _timer_stats.get("centroid", (0.0, 0, 0.0))
    print(
        f"  Avg: {avg_ms:.1f}ms | Total: {tot_us:.0f}us, "
        f"CLUSTER: {clus * 1e6:.0f}us, CENTROID: {cent * 1e6:.0f}us"
    )


# ---------------------------------------------------------------------------
# Optional sklearn import — gracefully degrade if not installed
# ---------------------------------------------------------------------------
try:
    from sklearn.cluster import DBSCAN as SklearnDBSCAN

    _HAS_SKLEARN = True
except Exception:
    # sklearn missing or broken (e.g. numpy version mismatch)
    _HAS_SKLEARN = False

# ---------------------------------------------------------------------------
# Optional cuML import — GPU-native DBSCAN (RAPIDS), zero CPU copies
# ---------------------------------------------------------------------------
try:
    from cuml.cluster import DBSCAN as CuMLDBSCAN

    _HAS_CUML = True
except Exception:
    _HAS_CUML = False


class DBSCAN3D:
    """3D DBSCAN clustering with sklearn backend and GPU centroid computation.

    Parameters
    ----------
    eps : float
        Maximum distance between two samples for them to be considered neighbours.
    min_samples : int
        Number of samples in a neighbourhood for a point to be a core point
        (including the point itself).
    metric : str
        Distance metric: ``'euclidean'``, ``'cosine'``, ``'manhattan'``,
        or ``'mahalanobis'``.
    scale_coords : bool
        Whether to apply per-dimension weights before computing distances
        (ignored when ``metric='mahalanobis'`` — the covariance matrix
        already captures relative scaling).
    x_weight, y_weight, z_weight : float
        Per-dimension multipliers (only used when ``scale_coords=True`` and
        ``metric != 'mahalanobis'``).
    measurement_noise_matrix : Tensor or ndarray, optional
        3×3 covariance matrix for Mahalanobis distance.
    device : str, optional
        Torch device. Defaults to CUDA if available, else CPU.
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
        self.eps_sq = eps * eps
        self.min_samples = min_samples
        self.metric = metric
        self.scale_coords = scale_coords
        self.x_weight = x_weight
        self.y_weight = y_weight
        self.z_weight = z_weight

        self.device = (
            torch.device(device)
            if device
            else torch.device("cuda" if torch.cuda.is_available() else "cpu")
        )

        if measurement_noise_matrix is None:
            self.measurement_noise_matrix = torch.eye(3, device=self.device)
        else:
            if isinstance(measurement_noise_matrix, np.ndarray):
                measurement_noise_matrix = torch.from_numpy(measurement_noise_matrix)
            self.measurement_noise_matrix = measurement_noise_matrix.float().to(
                self.device
            )

        # Inverse covariance for both PyTorch Mahalanobis AND sklearn/ cuML VI param.
        # Compute on CPU to avoid cuSOLVER init race (the matrix is 3×3 — ~1 us).
        self.measurement_noise_matrix_inv = torch.linalg.inv(
            self.measurement_noise_matrix.cpu()
        ).to(self.device)

        self.labels_ = None
        self.core_sample_indices_ = None
        self.n_clusters_ = 0
        self.cluster_centroids_ = {}

    # ------------------------------------------------------------------
    # Distance matrix (fallback when sklearn is unavailable)
    # ------------------------------------------------------------------
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
            mahal_inner = torch.einsum(
                "ijk,kl->ijl", diff, self.measurement_noise_matrix_inv
            )
            mahal_sq = torch.sum(diff * mahal_inner, dim=2)
            return torch.sqrt(torch.clamp(mahal_sq, min=0))

        raise ValueError(f"Unsupported metric: {self.metric}")

    def _get_neighbors_mask(self, distances: torch.Tensor) -> torch.Tensor:
        return distances <= self.eps

    def _weighted_median(
        self, values: torch.Tensor, weights: torch.Tensor
    ) -> torch.Tensor:
        sorted_idx = torch.argsort(values)
        values_sorted = values[sorted_idx]
        weights_sorted = weights[sorted_idx]

        cum_weights = torch.cumsum(weights_sorted, dim=0)
        cutoff = 0.5 * torch.sum(weights_sorted)

        median_idx = torch.searchsorted(cum_weights, cutoff)
        median_idx = torch.clamp(median_idx, 0, len(values_sorted) - 1)

        return values_sorted[median_idx]

    # ------------------------------------------------------------------
    # Fallback: CPU numpy BFS (used when sklearn is unavailable)
    # ------------------------------------------------------------------
    @staticmethod
    def _bfs_cluster_numpy(
        neighbors_mask: np.ndarray, is_core: np.ndarray
    ) -> Tuple[np.ndarray, int]:
        n = neighbors_mask.shape[0]
        labels = np.full(n, -1, dtype=np.int64)
        visited = np.zeros(n, dtype=bool)
        current_cluster = 1

        core_indices = np.where(is_core)[0]

        for core_idx in core_indices:
            if visited[core_idx] or labels[core_idx] != -1:
                continue

            visited[core_idx] = True
            labels[core_idx] = current_cluster

            neighbor_idxs = np.where(neighbors_mask[core_idx])[0]
            seeds = set(neighbor_idxs.tolist())

            while seeds:
                curr = seeds.pop()
                if visited[curr]:
                    continue
                visited[curr] = True

                if labels[curr] == -1:
                    labels[curr] = current_cluster

                if is_core[curr]:
                    new_neighbors = np.where(neighbors_mask[curr])[0]
                    for n_idx in new_neighbors:
                        if not visited[n_idx]:
                            seeds.add(n_idx)

            current_cluster += 1

        return labels, current_cluster

    # ------------------------------------------------------------------
    # Main fit method
    # ------------------------------------------------------------------
    def fit(
        self,
        detection_coords: torch.Tensor,
        detection_power=None,
        power_threshold: float = 0.0,
    ) -> "DBSCAN3D":
        _fit_tag = "fit [GPU]" if self.device.type == "cuda" else "fit [CPU]"
        _start_timer(_fit_tag)

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
        # Convert azimuth (deg) → spatial frequency u = π·sin(θ)
        angles_rad = torch.deg2rad(detection_coords[:, 2])
        detection_coords[:, 2] = np.pi * torch.sin(angles_rad)

        n_samples = detection_coords.shape[0]

        if n_samples == 0:
            self.labels_ = torch.tensor([], dtype=torch.long, device=self.device)
            self.n_clusters_ = 0
            self.cluster_centroids_ = {}
            _stop_timer(_fit_tag, level=2)
            _print_cycle_summary(_fit_tag)
            return self

        if detection_power is not None:
            if not isinstance(detection_power, torch.Tensor):
                detection_power = torch.tensor(detection_power, dtype=torch.float32)
            detection_power = detection_power.to(self.device).float()
        else:
            detection_power = torch.ones(n_samples, device=self.device)

        detection_power = torch.nan_to_num(
            detection_power,
            nan=0.0,
            neginf=0.0,
            posinf=120.0,
        )

        if self.metric == "mahalanobis":
            scaled_coords = detection_coords
        elif self.scale_coords:
            scaled_coords = detection_coords.clone()
            scaled_coords[:, 0] *= self.x_weight
            scaled_coords[:, 1] *= self.y_weight
            scaled_coords[:, 2] *= self.z_weight
        else:
            scaled_coords = detection_coords

        # ==============================================================
        # CLUSTERING  —  GPU via cuML  /  CPU via sklearn  /  fallback
        # ==============================================================
        _start_timer("cluster")
        if _HAS_CUML and self.device.type == "cuda":
            try:
                labels, n_initial_clusters, self.core_sample_indices_ = (
                    self._cluster_gpu(scaled_coords)
                )
            except Exception as exc:
                if DEBUG_LEVEL >= 1:
                    print(f"    cuML failed ({exc}); falling back to sklearn")
                if _HAS_SKLEARN:
                    labels_np, n_initial_clusters, core_indices_np = (
                        self._cluster_sklearn(scaled_coords)
                    )
                    self.core_sample_indices_ = torch.from_numpy(
                        core_indices_np.astype(np.int64)
                    ).to(self.device)
                    labels = torch.from_numpy(labels_np).to(
                        self.device, dtype=torch.long
                    )
                else:
                    raise
        elif _HAS_SKLEARN:
            labels_np, n_initial_clusters, core_indices_np = self._cluster_sklearn(
                scaled_coords
            )
            self.core_sample_indices_ = torch.from_numpy(
                core_indices_np.astype(np.int64)
            ).to(self.device)
            labels = torch.from_numpy(labels_np).to(self.device, dtype=torch.long)
        else:
            labels_np, n_initial_clusters = self._cluster_fallback(scaled_coords)
            core_indices_np = np.where(labels_np != -1)[0]
            self.core_sample_indices_ = torch.from_numpy(
                core_indices_np.astype(np.int64)
            ).to(self.device)
            labels = torch.from_numpy(labels_np).to(self.device, dtype=torch.long)
        _stop_timer("cluster", level=2)

        # ==============================================================
        # Centroid computation
        # ==============================================================
        _start_timer("centroid")
        self._compute_centroids(
            labels,
            detection_coords,
            detection_power,
            power_threshold,
            n_initial_clusters,
        )
        _stop_timer("centroid", level=2)

        self.labels_ = labels
        self.n_clusters_ = len(self.cluster_centroids_)
        _stop_timer(_fit_tag, level=2)
        _print_cycle_summary(_fit_tag)
        return self

    # ------------------------------------------------------------------
    # sklearn-accelerated clustering
    # ------------------------------------------------------------------
    def _cluster_sklearn(
        self, scaled_coords: torch.Tensor
    ) -> Tuple[np.ndarray, int, np.ndarray]:
        """Run DBSCAN via scikit-learn (tree-based search, Cython BFS)."""
        X_cpu = scaled_coords.cpu().numpy().astype(np.float64)

        # Prepare metric parameters
        sklearn_metric = self.metric
        sklearn_metric_params = {}
        if self.metric == "mahalanobis":
            VI_np = self.measurement_noise_matrix_inv.cpu().numpy()
            sklearn_metric_params["VI"] = VI_np

        clusterer = SklearnDBSCAN(
            eps=self.eps,
            min_samples=self.min_samples,
            metric=sklearn_metric,
            metric_params=sklearn_metric_params,
            algorithm="auto",
            n_jobs=-1,  # use all CPU cores
        )
        clusterer.fit(X_cpu)

        labels_raw = clusterer.labels_  # -1 = noise, 0,1,2,… = clusters
        core_indices = clusterer.core_sample_indices_.astype(np.int64)

        # Convert sklearn's 0-based cluster IDs to our 1-based convention
        labels_out = labels_raw.copy()
        labels_out[labels_out != -1] += 1

        # If all points are noise, max() is -1 — clamp to 0 so the
        # centroid loop range(1, 0) is empty.
        n_clusters = max(0, int(labels_out.max())) if labels_out.size > 0 else 0
        return labels_out, n_clusters, core_indices

    # ------------------------------------------------------------------
    # GPU-accelerated clustering via cuML DBSCAN
    # ------------------------------------------------------------------
    def _cluster_gpu(
        self, scaled_coords: torch.Tensor
    ) -> Tuple[torch.Tensor, int, torch.Tensor]:
        """Run DBSCAN entirely on GPU via cuML."""
        cuml_metric = self.metric
        cuml_metric_kwargs = {}
        if self.metric == "mahalanobis":
            cuml_metric_kwargs["VI"] = self.measurement_noise_matrix_inv

        clusterer = CuMLDBSCAN(
            eps=self.eps,
            min_samples=self.min_samples,
            metric=cuml_metric,
            metric_kwargs=cuml_metric_kwargs,
        )
        clusterer.fit(scaled_coords)

        labels_raw = torch.as_tensor(
            clusterer.labels_, device=self.device, dtype=torch.long
        )
        core_indices = torch.as_tensor(
            clusterer.core_sample_indices_,
            device=self.device,
            dtype=torch.long,
        )

        labels_out = labels_raw.clone()
        noise_mask = labels_out == -1
        labels_out += 1
        labels_out[noise_mask] = -1

        n_clusters = int(labels_out.max().item()) if labels_out.numel() > 0 else 0
        n_clusters = max(0, n_clusters)

        return labels_out, n_clusters, core_indices

    # ------------------------------------------------------------------
    # Fallback: PyTorch distance matrix + numpy BFS
    # ------------------------------------------------------------------
    def _cluster_fallback(self, scaled_coords: torch.Tensor) -> Tuple[np.ndarray, int]:
        """Compute distance matrix on GPU, BFS on CPU (no sklearn)."""
        distances = self._compute_distance_matrix(scaled_coords)
        neighbors_mask = self._get_neighbors_mask(distances)

        neighbor_counts = neighbors_mask.sum(dim=1)
        is_core = neighbor_counts >= self.min_samples

        # Bulk transfer to CPU
        neighbors_mask_np = neighbors_mask.cpu().numpy()
        is_core_np = is_core.cpu().numpy()

        labels_np, n_clusters = self._bfs_cluster_numpy(neighbors_mask_np, is_core_np)
        # n_clusters is already >= 1 (or labels are all noise)
        return labels_np, n_clusters

    # ------------------------------------------------------------------
    # Centroid computation  (GPU path  /  CPU path)
    # ------------------------------------------------------------------
    def _compute_centroids(
        self,
        labels: torch.Tensor,
        detection_coords: torch.Tensor,
        detection_power: torch.Tensor,
        power_threshold: float,
        n_initial_clusters: int,
    ) -> None:
        # Dispatch to the appropriate backend
        if self.device.type == "cuda":
            self._compute_centroids_gpu(
                labels,
                detection_coords,
                detection_power,
                power_threshold,
                n_initial_clusters,
            )
        else:
            self._compute_centroids_cpu(
                labels,
                detection_coords,
                detection_power,
                power_threshold,
                n_initial_clusters,
            )

    # ------------------------------------------------------------------
    def _compute_centroids_cpu(
        self,
        labels: torch.Tensor,
        detection_coords: torch.Tensor,
        detection_power: torch.Tensor,
        power_threshold: float,
        n_initial_clusters: int,
    ) -> None:
        """CPU-optimised path: single lexsort + numpy loop.

        ``np.lexsort((doppler, label))`` groups clusters AND pre-sorts
        doppler in one O(N log N) C-level pass.  The per-cluster loop
        uses numpy (near-zero dispatch cost for small arrays).
        """
        self.cluster_centroids_ = {}
        if n_initial_clusters <= 1:
            return

        _start_timer("centroid.sort")

        # Zero-copy numpy views (shares memory with the PyTorch tensors)
        labels_np = labels.cpu().numpy()
        coords_np = detection_coords.cpu().numpy()
        power_np = detection_power.cpu().numpy()

        # Single lexsort: primary=label, secondary=doppler
        order = np.lexsort((coords_np[:, 1], labels_np))
        s_labels = labels_np[order]
        s_coords = coords_np[order]
        s_power = power_np[order]

        # Segment boundaries
        changes = np.where(s_labels[:-1] != s_labels[1:])[0] + 1
        starts = np.concatenate([[0], changes])
        ends = np.concatenate([changes, [len(s_labels)]])

        _stop_timer("centroid.sort", level=2)

        _start_timer("centroid.loop")
        for si in range(len(starts)):
            lo, hi = starts[si], ends[si]
            cluster_id = s_labels[lo]
            if cluster_id < 1:
                continue

            seg_coords = s_coords[lo:hi]
            seg_power = s_power[lo:hi]
            n_pts = hi - lo

            max_pwr = seg_power.max()
            range_vals = seg_coords[:, 0]
            med_range = np.median(range_vals)
            range_bonus = 10.0 * np.log10(max(med_range, 1.0))

            if (max_pwr + range_bonus) < power_threshold:
                labels_np[order[lo:hi]] = -1
                continue

            p_sum = seg_power.sum()
            if p_sum <= 0:
                range_centroid = range_vals.mean()
                freq_centroid = seg_coords[:, 2].mean()
            else:
                w = seg_power / p_sum
                range_centroid = (w * range_vals).sum()
                freq_centroid = (w * seg_coords[:, 2]).sum()

            angle_centroid = np.arcsin(np.clip(freq_centroid / np.pi, -1.0, 1.0))

            # Doppler is pre-sorted by lexsort
            dop_vals = seg_coords[:, 1]
            if p_sum <= 0:
                doppler_centroid = dop_vals[n_pts // 2]
            else:
                csw = np.cumsum(seg_power)
                half = 0.5 * p_sum
                idx = np.searchsorted(csw, half)
                if idx >= n_pts:
                    idx = n_pts - 1
                doppler_centroid = dop_vals[idx]

            if abs(doppler_centroid) > 0:
                self.cluster_centroids_[int(cluster_id)] = (
                    torch.tensor(
                        [range_centroid, doppler_centroid, angle_centroid],
                        device=self.device,
                    ),
                    n_pts,
                )
        _stop_timer("centroid.loop", level=2)

    # ------------------------------------------------------------------
    def _compute_centroids_gpu(
        self,
        labels: torch.Tensor,
        detection_coords: torch.Tensor,
        detection_power: torch.Tensor,
        power_threshold: float,
        n_initial_clusters: int,
    ) -> None:
        """GPU-optimised path: vectorised scatter ops + global sort.

        All per-cluster aggregates are computed with O(1) scatter kernels
        (no Python loop over clusters).  The weighted median of Doppler
        uses a single global sort + segment extraction.

        Data is already on GPU when this is called (``fit()`` transfers
        it), so **no extra CPU-GPU copies** are incurred.
        """
        self.cluster_centroids_ = {}
        if n_initial_clusters <= 1:
            return

        device = self.device

        # --- 1. Non-noise points → contiguous index -------------------
        _start_timer("centroid.scatter")
        valid = labels >= 1
        if not valid.any():
            return

        cids = labels[valid]
        coords = detection_coords[valid]
        power = detection_power[valid]

        unique_ids, scatter_idx = torch.unique(cids, return_inverse=True)
        K = unique_ids.shape[0]

        # --- 2. Vectorised per-cluster aggregates (single pass) ------
        ones = torch.ones_like(power)
        cnt = torch.zeros(K, device=device, dtype=torch.float32)
        psum = torch.zeros(K, device=device, dtype=torch.float32)
        rsum = torch.zeros(K, device=device, dtype=torch.float32)
        fsum = torch.zeros(K, device=device, dtype=torch.float32)
        pmax = torch.zeros(K, device=device, dtype=torch.float32)

        cnt.scatter_add_(0, scatter_idx, ones)
        psum.scatter_add_(0, scatter_idx, power)
        rsum.scatter_add_(0, scatter_idx, power * coords[:, 0])
        fsum.scatter_add_(0, scatter_idx, power * coords[:, 2])
        pmax.scatter_reduce_(0, scatter_idx, power, reduce="amax", include_self=False)

        zero_power = psum <= 0
        if zero_power.any():
            rr = torch.zeros(K, device=device, dtype=torch.float32)
            ff = torch.zeros(K, device=device, dtype=torch.float32)
            rr.scatter_add_(0, scatter_idx, coords[:, 0])
            ff.scatter_add_(0, scatter_idx, coords[:, 2])
            psum[zero_power] = cnt[zero_power]
            rsum[zero_power] = rr[zero_power]
            fsum[zero_power] = ff[zero_power]

        # --- 3. Power threshold --------------------------------------
        _stop_timer("centroid.scatter", level=2)

        range_est = rsum / psum
        range_bonus = 10.0 * torch.log10(torch.clamp(range_est, min=1.0))
        effective = pmax + range_bonus
        keep = (effective >= power_threshold) & (cnt > 0)

        if (~keep).any():
            reject_ids = unique_ids[~keep]
            n_ids = n_initial_clusters + 1
            rej_flag = torch.zeros(n_ids, dtype=torch.bool, device=device)
            rej_flag[reject_ids] = True
            labels.masked_fill_(rej_flag[labels.clamp(min=0)], -1)

        kept = torch.where(keep)[0]
        if kept.shape[0] == 0:
            return

        K_keep = kept.shape[0]
        kept_ids = unique_ids[kept]

        r_cent = rsum[kept] / psum[kept]
        f_cent = fsum[kept] / psum[kept]
        a_cent = torch.arcsin(torch.clamp(f_cent / np.pi, -1.0, 1.0))
        sizes = cnt[kept].to(torch.int64)

        # --- 4. Weighted median of Doppler  (global sort + extract) --
        _start_timer("centroid.gpumedian")
        keep_pt = torch.isin(labels, kept_ids)
        k_coords = detection_coords[keep_pt]
        k_power = detection_power[keep_pt]
        k_labels = labels[keep_pt]

        _, k_idx = torch.unique(k_labels, return_inverse=True)

        zero_kept = zero_power[kept]
        if zero_kept.any():
            k_power = k_power.clone()
            k_power[zero_kept[k_idx]] = 1.0

        dop = k_coords[:, 1]
        dmin = dop.min()
        drng = (dop.max() - dmin).clamp(min=1e-10)
        dnorm = ((dop - dmin) / drng).clamp(max=1.0 - 1e-10)

        packed = k_idx.float() + dnorm
        order = torch.argsort(packed)

        s_dop = dop[order]
        s_pwr = k_power[order]
        s_idx = k_idx[order]

        half = torch.zeros(K_keep, device=device, dtype=torch.float32)
        half.scatter_add_(0, s_idx, s_pwr)
        half *= 0.5

        cum = torch.cumsum(s_pwr, dim=0)
        excess = cum - half[s_idx]

        seg_start = torch.cat(
            [
                torch.tensor([True], device=device),
                s_idx[1:] != s_idx[:-1],
            ]
        )
        prev_below = torch.cat(
            [
                torch.tensor([True], device=device),
                excess[:-1] < 0,
            ]
        )
        median_cand = (excess >= 0) & (seg_start | prev_below)

        pos = torch.arange(len(s_dop), device=device, dtype=torch.float32)
        cand = torch.where(median_cand, pos, torch.full_like(pos, float("inf")))
        first = torch.full((K_keep,), float("inf"), device=device, dtype=torch.float32)
        first.scatter_reduce_(0, s_idx, cand, reduce="amin", include_self=False)

        d_cent = torch.zeros(K_keep, device=device, dtype=torch.float32)
        ok = torch.isfinite(first)
        d_cent[ok] = s_dop[first[ok].long()]

        # --- 5. Build output dict  (small loop) ----------------------
        _stop_timer("centroid.gpumedian", level=2)

        for i in range(K_keep):
            if d_cent[i].abs() > 0:
                cid = kept_ids[i].item()
                self.cluster_centroids_[cid] = (
                    torch.tensor(
                        [r_cent[i].item(), d_cent[i].item(), a_cent[i].item()],
                        device=device,
                    ),
                    sizes[i].item(),
                )

    # ------------------------------------------------------------------
    # fit_predict
    # ------------------------------------------------------------------
    def fit_predict(
        self,
        detection_coords: np.ndarray,
        detection_power=None,
        power_threshold: float = 0.0,
    ) -> np.ndarray:
        if len(detection_coords) == 0:
            return np.array([], dtype=np.int32)

        if detection_coords.ndim != 2 or detection_coords.shape[1] != 3:
            raise ValueError(
                f"Expected shape (n_detections, 3), got {detection_coords.shape}"
            )

        self.fit(detection_coords, detection_power, power_threshold)

        labels_cpu = self.labels_.cpu().numpy()
        output_labels = labels_cpu.copy()

        valid_labels = labels_cpu[labels_cpu != -1]
        noise_cluster_id = int(valid_labels.max()) + 1 if len(valid_labels) > 0 else 1

        # Give each noise point a unique positive label for visualization.
        for i in range(len(labels_cpu)):
            if labels_cpu[i] == -1:
                output_labels[i] = noise_cluster_id
                noise_cluster_id += 1

        return output_labels.astype(np.int32)


# --------------------------------------------------------------------------
# Module-level convenience functions
# --------------------------------------------------------------------------


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
            min_samples=config.MIN_SAMPLES,
            metric="mahalanobis",
            scale_coords=True,
            x_weight=config.SIGMA_RANGE,
            y_weight=config.SIGMA_DOPPLER,
            z_weight=config.SIGMA_AZIMUTH,
            measurement_noise_matrix=config.MEASUREMENT_NOISE,
            device="cpu",  # auto-detect CUDA
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
