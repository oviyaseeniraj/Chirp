"""
Chirp  –  Closed-form self-calibration math
===========================================
Ported from Fusion-Center/server_controller.py

Given per-node frame data (track x,y positions keyed by frame index),
solves for the pairwise rotation (theta_deg) and translation (P)
between radar nodes using RANSAC + network averaging.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Tunable parameters
# ---------------------------------------------------------------------------
CALIB_MIN_TRACK_FRAMES = 50  # min frames a track_id must appear in (single-target)
CALIB_MIN_TRAJECTORY_FRAMES = 25  # min frames required before attempting solve

_RANSAC_SUBSET_SIZE = 10
_RANSAC_NUM_TRIALS = 200
_RANSAC_INLIER_THRESHOLD = 0.5  # metres
_RANSAC_MIN_INLIER_RATIO = 0.25
_RANSAC_RESIDUAL_THRESHOLD = 0.25  # reject pair if RMSE² exceeds this

log = logging.getLogger("calibration.math")


# ---------------------------------------------------------------------------
# Pairwise closed-form solver
# ---------------------------------------------------------------------------


def _closed_form_pair(z_i: np.ndarray, z_k: np.ndarray) -> Tuple[float, complex, float]:
    """Closed-form calibration for one radar pair from complex trajectories.

    Returns (phi_rad, P, J) where:
        phi_rad : rotation angle such that theta_deg = -deg(phi)
        P       : complex translation  z_i ≈ P + exp(-j*phi) * z_k
        J       : least-squares residual (sum)
    """
    z_i_mean = np.mean(z_i)
    z_k_mean = np.mean(z_k)
    val = np.sum((z_k - z_k_mean) * np.conj(z_i - z_i_mean))
    phi = float(np.arctan2(val.imag, val.real))
    P = z_i_mean - np.exp(-1j * phi) * z_k_mean
    J = float(
        np.sum(np.abs(z_i - z_i_mean) ** 2)
        + np.sum(np.abs(z_k - z_k_mean) ** 2)
        - 2.0 * abs(val)
    )
    if J < 0 and abs(J) < 1e-10:
        J = 0.0
    return phi, P, J


def _ransac_pair(
    z_i: np.ndarray,
    z_k: np.ndarray,
) -> Tuple[float, complex, float, float, float]:
    """RANSAC-robust closed-form calibration for one radar pair.

    Returns (phi_rad, P, rmse_sq, inlier_ratio, weight).
    """
    T = len(z_i)
    min_inliers = max(_RANSAC_SUBSET_SIZE, int(np.ceil(_RANSAC_MIN_INLIER_RATIO * T)))

    best_inliers = np.ones(T, dtype=bool)
    best_num_inliers = 0
    best_rmse = np.inf
    best_spread = -np.inf

    det_idx = np.unique(
        np.round(np.linspace(0, T - 1, _RANSAC_SUBSET_SIZE)).astype(int)
    )

    for trial in range(_RANSAC_NUM_TRIALS):
        rng = np.random.default_rng(trial)
        sample_idx = (
            det_idx if trial == 0 else rng.choice(T, _RANSAC_SUBSET_SIZE, replace=False)
        )

        phi_hyp, P_hyp, _ = _closed_form_pair(z_i[sample_idx], z_k[sample_idx])
        residuals = np.abs(z_i - (P_hyp + np.exp(-1j * phi_hyp) * z_k))
        inliers = residuals <= _RANSAC_INLIER_THRESHOLD
        n_in = int(np.sum(inliers))

        if n_in == 0:
            continue

        rmse = float(np.sqrt(np.mean(residuals[inliers] ** 2)))
        spread = float(
            np.sqrt(np.mean(np.abs(z_i[inliers] - np.mean(z_i[inliers])) ** 2))
        )

        better = (
            n_in > best_num_inliers
            or (n_in == best_num_inliers and rmse < best_rmse)
            or (
                n_in == best_num_inliers
                and abs(rmse - best_rmse) < 1e-12
                and spread > best_spread
            )
        )
        if better:
            best_inliers = inliers
            best_num_inliers = n_in
            best_rmse = rmse
            best_spread = spread

    if best_num_inliers < min_inliers:
        best_inliers = np.ones(T, dtype=bool)

    final_K = int(np.sum(best_inliers))
    phi_final, P_final, J_final = _closed_form_pair(
        z_i[best_inliers], z_k[best_inliers]
    )
    rmse_sq = J_final / final_K if final_K > 0 else np.inf
    inlier_ratio = final_K / T
    weight = inlier_ratio / (rmse_sq + 1e-12)

    return phi_final, P_final, rmse_sq, inlier_ratio, weight


# ---------------------------------------------------------------------------
# Network-level weighted averaging
# ---------------------------------------------------------------------------


def _network_average(
    P_raw: np.ndarray,
    theta_raw: np.ndarray,
    pair_weights: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Weighted graph-style network averaging over direct + indirect paths.

    For each (ref, i) entry averages:
      - Direct path:  P[ref,i], weight = pair_weights[ref,i]
      - Indirect via k: P[ref,k] + exp(j*theta[ref,k]) * P[k,i],
                        weight = min(pair_weights[ref,k], pair_weights[k,i])

    Angle averaging uses complex exponentials for wrap-around.
    """
    N = P_raw.shape[0]
    P_opt = np.zeros((N, N), dtype=np.complex128)
    theta_opt = np.zeros((N, N), dtype=np.float64)
    weight_opt = np.zeros((N, N), dtype=np.float64)

    for ref in range(N):
        for i in range(N):
            if i == ref:
                continue

            sum_P = np.complex128(0)
            sum_exp = np.complex128(0)
            total_w = 0.0

            for k in range(N):
                w = 0.0
                P_path = np.complex128(0)
                theta_path_rad = 0.0

                if k == ref:
                    # Direct path ref → i
                    if pair_weights[ref, i] > 0:
                        w = pair_weights[ref, i]
                        P_path = P_raw[ref, i]
                        theta_path_rad = np.deg2rad(theta_raw[ref, i])
                else:
                    # Indirect: ref → k → i
                    wk_ref = pair_weights[ref, k]
                    wk_i = pair_weights[k, i]
                    if wk_ref > 0 and wk_i > 0:
                        w = min(wk_ref, wk_i)
                        # Accumulate: z_i ≈ z_ref + P[ref,k] + exp(j*theta[ref,k])*P[k,i]
                        exp_j = np.exp(1j * np.deg2rad(theta_raw[ref, k]))
                        P_path = P_raw[ref, k] + exp_j * P_raw[k, i]
                        theta_path_rad = np.deg2rad(theta_raw[ref, k] + theta_raw[k, i])

                if w > 0:
                    sum_P += w * P_path
                    sum_exp += w * np.exp(1j * theta_path_rad)
                    total_w += w

            if total_w > 0:
                P_opt[ref, i] = sum_P / total_w
                theta_opt[ref, i] = np.rad2deg(float(np.angle(sum_exp)))
                weight_opt[ref, i] = total_w

    return P_opt, theta_opt, weight_opt


# ---------------------------------------------------------------------------
# Top-level calibration entry point
# ---------------------------------------------------------------------------


def closed_form_calibration(
    frame_data: Dict[str, Dict[int, List]],
) -> Tuple[
    Optional[List[str]],
    Optional[np.ndarray],
    Optional[np.ndarray],
    Optional[Dict[str, Any]],
]:
    """Robust pairwise self-calibration across multiple radar nodes.

    Parameters
    ----------
    frame_data : node_id -> frame_idx -> list of {"track_id": int, "x": float, "y": float}

    Returns
    -------
    node_ids   : ordered list of node IDs
    P_opt      : fused complex translation matrix  (num_nodes × num_nodes)
    theta_opt  : fused rotation matrix in degrees  (num_nodes × num_nodes)
    solve_meta : calibration quality summary per pair
    """
    node_ids = list(frame_data.keys())
    num_nodes = len(node_ids)
    if num_nodes < 2:
        return None, None, None, {"reason": "need_at_least_two_nodes"}

    P_raw = np.zeros((num_nodes, num_nodes), dtype=np.complex128)
    theta_raw = np.zeros((num_nodes, num_nodes), dtype=np.float64)
    pair_weights = np.zeros((num_nodes, num_nodes), dtype=np.float64)
    ransac_meta: Dict[str, Any] = {}

    for i in range(num_nodes):
        for k in range(num_nodes):
            if i == k:
                continue

            ni, nk = node_ids[i], node_ids[k]
            pair_key = f"{ni}->{nk}"

            # 1. Per-pair frame intersection
            pair_common = sorted(frame_data[ni].keys() & frame_data[nk].keys())
            if not pair_common:
                ransac_meta[pair_key] = {"solved": False, "reason": "no_common_frames"}
                continue

            # 2. Single-target filter
            pair_single = [
                f
                for f in pair_common
                if len(frame_data[ni].get(f, [])) == 1
                and len(frame_data[nk].get(f, [])) == 1
            ]
            if not pair_single:
                ransac_meta[pair_key] = {
                    "solved": False,
                    "reason": "no_single_target_frames",
                    "commonFrames": len(pair_common),
                }
                continue

            # 3. Track lifetime filter
            track_count_i: Dict[int, int] = {}
            track_count_k: Dict[int, int] = {}
            for f in pair_single:
                tid_i = int(frame_data[ni][f][0]["track_id"])
                tid_k = int(frame_data[nk][f][0]["track_id"])
                track_count_i[tid_i] = track_count_i.get(tid_i, 0) + 1
                track_count_k[tid_k] = track_count_k.get(tid_k, 0) + 1

            pair_filtered = [
                f
                for f in pair_single
                if track_count_i.get(int(frame_data[ni][f][0]["track_id"]), 0)
                >= CALIB_MIN_TRACK_FRAMES
                and track_count_k.get(int(frame_data[nk][f][0]["track_id"]), 0)
                >= CALIB_MIN_TRACK_FRAMES
            ]

            if len(pair_filtered) < CALIB_MIN_TRAJECTORY_FRAMES:
                ransac_meta[pair_key] = {
                    "solved": False,
                    "reason": "insufficient_frames",
                    "commonFrames": len(pair_common),
                    "singleTargetFrames": len(pair_single),
                    "lifetimeFilteredFrames": len(pair_filtered),
                }
                continue

            # 4. Build complex trajectory
            zi = np.array(
                [
                    complex(
                        float(frame_data[ni][f][0]["x"]),
                        float(frame_data[ni][f][0]["y"]),
                    )
                    for f in pair_filtered
                ]
            )
            zk = np.array(
                [
                    complex(
                        float(frame_data[nk][f][0]["x"]),
                        float(frame_data[nk][f][0]["y"]),
                    )
                    for f in pair_filtered
                ]
            )

            # 5. RANSAC solve
            phi, P, rmse_sq, inlier_ratio, weight = _ransac_pair(zi, zk)

            if rmse_sq > _RANSAC_RESIDUAL_THRESHOLD:
                ransac_meta[pair_key] = {
                    "solved": False,
                    "reason": "residual_above_threshold",
                    "commonFrames": len(pair_common),
                    "rmse_sq": round(float(rmse_sq), 6),
                    "inlier_ratio": round(float(inlier_ratio), 4),
                }
                continue

            P_raw[i, k] = P
            theta_raw[i, k] = float(np.rad2deg(-phi))
            pair_weights[i, k] = weight
            ransac_meta[pair_key] = {
                "solved": True,
                "rmse_sq": round(float(rmse_sq), 6),
                "inlier_ratio": round(float(inlier_ratio), 4),
                "weight": round(float(weight), 4),
            }

    if not np.any(pair_weights > 0):
        return (
            None,
            None,
            None,
            {"reason": "no_pairs_solved", "ransacMetaByPair": ransac_meta},
        )

    P_opt, theta_opt, _weight_opt = _network_average(P_raw, theta_raw, pair_weights)
    solve_meta = {"networked": True, "ransacMetaByPair": ransac_meta}
    return node_ids, P_opt, theta_opt, solve_meta
