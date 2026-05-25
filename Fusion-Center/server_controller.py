#!/usr/bin/env python3
"""Jetson Xavier MQTT server control service (step 2 rollout)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import paho.mqtt.client as mqtt


SCHEMA_VERSION = 1
TOPIC_PREFIX = "chirp/v1"
START_REQUEST_TOPIC = f"{TOPIC_PREFIX}/server/start/request"        # subscribed topic
START_RESULT_TOPIC = f"{TOPIC_PREFIX}/server/start/result"          # published topic
SERVER_STATUS_TOPIC = f"{TOPIC_PREFIX}/server/status"               # published topic
PRESENCE_TOPIC_FILTER = f"{TOPIC_PREFIX}/presence/+"                # subscribed topic
STATE_TOPIC_FILTER = f"{TOPIC_PREFIX}/group/+/capture/state/+"      # subscribed topic
ACK_TOPIC_FILTER = f"{TOPIC_PREFIX}/group/+/capture/ack/+"          # subscribed topic
CALIB_FRAME_TOPIC_FILTER = f"{TOPIC_PREFIX}/group/+/calibration/frame/+"  # subscribed
CALIB_DONE_TOPIC_FILTER = f"{TOPIC_PREFIX}/group/+/calibration/done/+"    # subscribed

# Calibration quality parameters
CALIB_MIN_TRACK_FRAMES = 50       # min frames a track_id must appear in (single-target) to be trusted
CALIB_MIN_TRAJECTORY_FRAMES = 25  # min frames surviving all filters before attempting solve

# RANSAC parameters (mirror MATLAB's get_ransac_closed_form_solution defaults)
_RANSAC_SUBSET_SIZE = 10
_RANSAC_NUM_TRIALS = 200
_RANSAC_INLIER_THRESHOLD = 0.5   # metres
_RANSAC_MIN_INLIER_RATIO = 0.25
_RANSAC_RESIDUAL_THRESHOLD = 0.25  # reject pair if RMSE² exceeds this


def _closed_form_pair(
    z_i: np.ndarray, z_k: np.ndarray
) -> Tuple[float, complex, float]:
    """
    Closed-form calibration for one radar pair from complex trajectories.

    Returns (phi_rad, P, J) where:
      phi_rad : rotation angle such that theta_deg = -deg(phi)
      P       : complex translation  z_i ≈ P + exp(-j*phi) * z_k
      J       : least-squares residual (sum, not per-frame)
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
    subset_size: int = _RANSAC_SUBSET_SIZE,
    num_trials: int = _RANSAC_NUM_TRIALS,
    inlier_threshold: float = _RANSAC_INLIER_THRESHOLD,
    min_inlier_ratio: float = _RANSAC_MIN_INLIER_RATIO,
) -> Tuple[float, complex, float, float, float]:
    """
    RANSAC-robust closed-form calibration for one radar pair.

    Returns (phi_rad, P, rmse_sq, inlier_ratio, weight) where:
      rmse_sq      = J_final / num_inliers  (RMSE²)
      inlier_ratio = num_inliers / T
      weight       = inlier_ratio / (rmse_sq + eps)
    """
    T = len(z_i)
    min_inliers = max(subset_size, int(np.ceil(min_inlier_ratio * T)))

    best_inliers = np.ones(T, dtype=bool)  # fallback: all frames
    best_num_inliers = 0
    best_rmse = np.inf
    best_spread = -np.inf

    # Trial 0 is deterministic (evenly-spaced) for repeatability.
    det_idx = np.unique(np.round(np.linspace(0, T - 1, subset_size)).astype(int))

    for trial in range(num_trials):
        sample_idx = det_idx if trial == 0 else np.random.choice(T, subset_size, replace=False)

        phi_hyp, P_hyp, _ = _closed_form_pair(z_i[sample_idx], z_k[sample_idx])
        residuals = np.abs(z_i - (P_hyp + np.exp(-1j * phi_hyp) * z_k))
        inliers = residuals <= inlier_threshold
        n_in = int(np.sum(inliers))

        if n_in == 0:
            continue

        rmse = float(np.sqrt(np.mean(residuals[inliers] ** 2)))
        spread = float(np.sqrt(np.mean(np.abs(z_i[inliers] - np.mean(z_i[inliers])) ** 2)))

        better = (
            n_in > best_num_inliers
            or (n_in == best_num_inliers and rmse < best_rmse)
            or (n_in == best_num_inliers and abs(rmse - best_rmse) < 1e-12 and spread > best_spread)
        )
        if better:
            best_inliers = inliers
            best_num_inliers = n_in
            best_rmse = rmse
            best_spread = spread

    # If RANSAC found insufficient consensus fall back to all frames.
    if best_num_inliers < min_inliers:
        best_inliers = np.ones(T, dtype=bool)

    final_K = int(np.sum(best_inliers))
    phi_final, P_final, J_final = _closed_form_pair(z_i[best_inliers], z_k[best_inliers])
    rmse_sq = J_final / final_K if final_K > 0 else np.inf
    inlier_ratio = final_K / T
    weight = inlier_ratio / (rmse_sq + 1e-12)

    return phi_final, P_final, rmse_sq, inlier_ratio, weight


def _network_average(
    P_raw: np.ndarray,
    theta_raw: np.ndarray,
    pair_weights: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Weighted graph-style network averaging (port of get_averaged_calibration.m, robust version).

    For each (ref, i) entry averages:
      - Direct path  (k = ref): P[ref,i], weight = pair_weights[ref,i]
      - Indirect via k:         P[ref,k] + exp(j*theta[ref,k]) * P[k,i],
                                weight = min(pair_weights[ref,k], pair_weights[k,i])

    Angle averaging uses complex exponentials to handle wrap-around correctly.
    Paths with zero weight (unsolved pairs) are skipped.
    Falls back to the direct estimate when no indirect paths are valid.

    Returns (P_fused, theta_fused, weight_fused).
    """
    num_nodes = P_raw.shape[0]
    P_fused = np.zeros((num_nodes, num_nodes), dtype=np.complex128)
    theta_fused = np.zeros((num_nodes, num_nodes), dtype=np.float64)
    weight_fused = np.zeros((num_nodes, num_nodes), dtype=np.float64)

    for ref in range(num_nodes):
        for i in range(num_nodes):
            if ref == i:
                continue

            pos_num = 0.0 + 0.0j
            theta_num = 0.0 + 0.0j
            weight_sum = 0.0

            for k in range(num_nodes):
                if k == i:
                    # Skipping k==i avoids double-counting the direct path
                    continue

                if k == ref:
                    # Direct path (ref -> i)
                    w = pair_weights[ref, i]
                    if w <= 0.0:
                        continue
                    candidate_P = P_raw[ref, i]
                    candidate_theta_rad = np.deg2rad(theta_raw[ref, i])
                    path_weight = w
                else:
                    # Indirect path via k: (ref -> k -> i)
                    w_rk = pair_weights[ref, k]
                    w_ki = pair_weights[k, i]
                    if w_rk <= 0.0 or w_ki <= 0.0:
                        continue
                    candidate_P = (
                        P_raw[ref, k]
                        + np.exp(1j * np.deg2rad(theta_raw[ref, k])) * P_raw[k, i]
                    )
                    candidate_theta_rad = np.deg2rad(
                        theta_raw[ref, k] + theta_raw[k, i]
                    )
                    path_weight = min(w_rk, w_ki)

                pos_num += path_weight * candidate_P
                theta_num += path_weight * np.exp(1j * candidate_theta_rad)
                weight_sum += path_weight

            if weight_sum > 0.0:
                P_fused[ref, i] = pos_num / weight_sum
                theta_fused[ref, i] = float(np.rad2deg(np.angle(theta_num))) % 360.0
                weight_fused[ref, i] = weight_sum
            else:
                # Fallback: use direct estimate as-is
                P_fused[ref, i] = P_raw[ref, i]
                theta_fused[ref, i] = float(theta_raw[ref, i]) % 360.0
                weight_fused[ref, i] = pair_weights[ref, i]

    return P_fused, theta_fused, weight_fused


def closed_form_calibration(
    frame_data: Dict[str, Dict[int, List]],
    min_track_frames: int = CALIB_MIN_TRACK_FRAMES,
    min_trajectory_frames: int = CALIB_MIN_TRAJECTORY_FRAMES,
) -> Tuple[
    Optional[List[str]],
    Optional[np.ndarray],
    Optional[np.ndarray],
    Optional[Dict[str, Any]],
]:
    """
    Robust pairwise self-calibration across multiple radar nodes.

    Parameters
    ----------
    frame_data : node_id -> frame_idx -> list of {"track_id": int, "x": float, "y": float}

    Pipeline (per radar pair)
    -------------------------
    1. Per-pair frame intersection: only the two nodes in the pair need a common frame.
    2. Single-target filter: both nodes must have exactly 1 confirmed track in the frame.
    3. Track lifetime filter: each node's track_id must appear in >= min_track_frames
       single-target frames before its positions are trusted.
    4. Build complex trajectory: z = x + j*y from EKF Cartesian state.
    5. RANSAC closed-form solve with quality gate (rmse_sq < _RANSAC_RESIDUAL_THRESHOLD).
    6. Network averaging: fuse direct + indirect paths using RANSAC weights.

    Returns
    -------
    node_ids   : ordered list of node IDs
    P_opt      : fused complex translation matrix  (num_nodes x num_nodes)
    theta_opt  : fused rotation matrix in degrees  (num_nodes x num_nodes)
    solve_meta : calibration quality summary per pair + network flag
    Returns (None, None, None, meta) when no pairs could be solved.
    """
    node_ids = list(frame_data.keys())
    num_nodes = len(node_ids)
    if num_nodes < 2:
        return None, None, None, None

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

            # 1. Per-pair frame intersection.
            pair_common = sorted(frame_data[ni].keys() & frame_data[nk].keys())
            if not pair_common:
                logging.warning("[CALIB] No common frames for pair %s", pair_key)
                ransac_meta[pair_key] = {"solved": False, "reason": "no_common_frames"}
                continue

            # 2. Single-target filter: both nodes must have exactly 1 track.
            pair_single = [
                f for f in pair_common
                if len(frame_data[ni].get(f, [])) == 1
                and len(frame_data[nk].get(f, [])) == 1
            ]
            if not pair_single:
                logging.warning("[CALIB] No single-target frames for pair %s", pair_key)
                ransac_meta[pair_key] = {
                    "solved": False,
                    "reason": "no_single_target_frames",
                    "commonFrames": len(pair_common),
                }
                continue

            # 3. Track lifetime filter.
            track_count_i: Dict[int, int] = {}
            track_count_k: Dict[int, int] = {}
            for f in pair_single:
                tid_i = int(frame_data[ni][f][0]["track_id"])
                tid_k = int(frame_data[nk][f][0]["track_id"])
                track_count_i[tid_i] = track_count_i.get(tid_i, 0) + 1
                track_count_k[tid_k] = track_count_k.get(tid_k, 0) + 1

            pair_filtered = [
                f for f in pair_single
                if track_count_i.get(int(frame_data[ni][f][0]["track_id"]), 0) >= min_track_frames
                and track_count_k.get(int(frame_data[nk][f][0]["track_id"]), 0) >= min_track_frames
            ]

            if len(pair_filtered) < min_trajectory_frames:
                logging.warning(
                    "[CALIB] Too few frames for pair %s: common=%d single=%d lifetime=%d (need %d)",
                    pair_key, len(pair_common), len(pair_single),
                    len(pair_filtered), min_trajectory_frames,
                )
                ransac_meta[pair_key] = {
                    "solved": False,
                    "reason": "insufficient_frames_after_filtering",
                    "commonFrames": len(pair_common),
                    "singleTargetFrames": len(pair_single),
                    "lifetimeFilteredFrames": len(pair_filtered),
                }
                continue

            # 4. Build complex trajectory for this pair.
            zi = np.array([
                complex(
                    float(frame_data[ni][f][0]["x"]),
                    float(frame_data[ni][f][0]["y"]),
                )
                for f in pair_filtered
            ])
            zk = np.array([
                complex(
                    float(frame_data[nk][f][0]["x"]),
                    float(frame_data[nk][f][0]["y"]),
                )
                for f in pair_filtered
            ])

            # 5. RANSAC closed-form solve with quality gate.
            phi, P, rmse_sq, inlier_ratio, weight = _ransac_pair(zi, zk)

            if rmse_sq > _RANSAC_RESIDUAL_THRESHOLD:
                logging.warning(
                    "[CALIB] Pair %s rejected: rmse_sq=%.4f > threshold=%.4f"
                    " inlier_ratio=%.2f",
                    pair_key, rmse_sq, _RANSAC_RESIDUAL_THRESHOLD, inlier_ratio,
                )
                ransac_meta[pair_key] = {
                    "solved": False,
                    "reason": "residual_above_threshold",
                    "commonFrames": len(pair_common),
                    "singleTargetFrames": len(pair_single),
                    "lifetimeFilteredFrames": len(pair_filtered),
                    "rmse_sq": round(float(rmse_sq), 6),
                    "inlier_ratio": round(float(inlier_ratio), 4),
                }
                continue

            P_raw[i, k] = P
            theta_raw[i, k] = float(np.rad2deg(-phi))
            pair_weights[i, k] = weight
            ransac_meta[pair_key] = {
                "solved": True,
                "commonFrames": len(pair_common),
                "singleTargetFrames": len(pair_single),
                "lifetimeFilteredFrames": len(pair_filtered),
                "rmse_sq": round(float(rmse_sq), 6),
                "inlier_ratio": round(float(inlier_ratio), 4),
                "weight": round(float(weight), 4),
            }

    if not np.any(pair_weights > 0):
        logging.warning("[CALIB] No radar pairs passed calibration criteria")
        return None, None, None, {
            "reason": "no_pairs_solved",
            "ransacMetaByPair": ransac_meta,
        }

    # 6. Network-level weighted averaging over direct + indirect paths.
    P_opt, theta_opt, weight_opt = _network_average(P_raw, theta_raw, pair_weights)

    solve_meta = {
        "networked": True,
        "ransacMetaByPair": ransac_meta,
    }
    return node_ids, P_opt, theta_opt, solve_meta

# Helper functions
def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        logging.warning("Invalid integer for %s=%r; using default=%d", name, value, default)
        return default


def _now_ms() -> int:
    return int(time.time() * 1000)


def _canonical_json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

# this ActiveCommand dataclass can be thought of a "struct" that holds metadata associated with each start command sent from laptop --> server
@dataclass
class ActiveCommand:
    command_id: str
    group_id: str
    requested_at_ms: int
    start_epoch_ms: int
    deadline_ms: int
    request_id: Optional[str]
    target_nodes: Set[str]
    capture_config: Any
    config_hash: str
    ack_map: Dict[str, Dict[str, Any]]
    lock: threading.Lock
    done: bool = False


@dataclass
class CalibrationSession:
    """Tracks per-node calibration frame data for one commandId."""
    command_id: str
    group_id: str
    target_nodes: Set[str]
    # node_id -> relative_frame_idx -> list of {"track_id": int, "x": float, "y": float}
    frame_data: Dict[str, Dict[int, List]] = field(default_factory=dict)
    done_nodes: Set[str] = field(default_factory=set)
    created_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    lock: threading.Lock = field(default_factory=threading.Lock)


class ServerController:
    """Coordinates group capture starts from laptop start requests."""

    def __init__(self) -> None:
        # all this code is essentially reading values from .env files or values sourced from the start_server_controller.sh script
        # if os.getenv() can't find the specified string in the 1st argument, then it will assign a default value specified in the 2nd argument
        self.mqtt_host = os.getenv("MQTT_HOST", "127.0.0.1") # os.getenv is used for strings
        self.mqtt_port = _env_int("MQTT_PORT", 1883) # _env_int() is used for integers
        self.client_id = os.getenv("MQTT_CLIENT_ID", "server-xavier")
        self.mqtt_user = os.getenv("MQTT_USERNAME", os.getenv("MQTT_SERVER_USER", "server-xavier"))
        self.mqtt_pass = os.getenv("MQTT_PASSWORD", os.getenv("MQTT_SERVER_PASS", ""))

        self.lead_time_ms = _env_int("CHIRP_LEAD_TIME_MS", 5000)
        self.min_start_delay_ms = _env_int("CHIRP_MIN_START_DELAY_MS", 1000)
        self.max_start_delay_ms = _env_int("CHIRP_MAX_START_DELAY_MS", 10000)
        self.ack_timeout_ms = _env_int("CHIRP_ACK_TIMEOUT_MS", 5000)
        self.presence_stale_ms = _env_int("CHIRP_PRESENCE_STALE_MS", 6000)
        self.state_stale_ms = _env_int("CHIRP_STATE_STALE_MS", 10000)

        self.shutdown_event = threading.Event()
        self.presence_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.command_lock = threading.Lock()
        self.calib_lock = threading.Lock()

        self.presence: Dict[str, Dict[str, Any]] = {} # what nodes are alive?
        self.state: Dict[Tuple[str, str], Dict[str, Any]] = {} # what state are the nodes in? the tuple is (group_id, node_id)
        self.active_commands: Dict[str, ActiveCommand] = {}
        self.calib_sessions: Dict[str, CalibrationSession] = {}  # commandId -> session 
        self.calibration_logs_dir = Path(__file__).resolve().parent / "logs" / "calibration_artifacts"
        self.calibration_logs_dir.mkdir(parents=True, exist_ok=True)

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            clean_session=False,
        )
        if self.mqtt_user:
            self.client.username_pw_set(self.mqtt_user, self.mqtt_pass)

        # configure the LWT (last will and testament) message; LWT msg is used to publish the status of the server if it unexpectedly crashes
        will_payload = {
            "schemaVersion": SCHEMA_VERSION,
            "serverId": self.client_id,
            "status": "offline",
            "timestampMs": _now_ms(),
        }
        self.client.will_set(
            SERVER_STATUS_TOPIC,
            payload=json.dumps(will_payload),
            qos=1,
            retain=True,
        )

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message # run _on_message() when a msg from subscribed topic arrives
        self.client.on_disconnect = self._on_disconnect

    def run(self) -> None:
        self.client.connect(self.mqtt_host, self.mqtt_port, keepalive=30)
        self.client.loop_start()

        logging.info("Server controller running with clientId=%s", self.client_id)
        while not self.shutdown_event.is_set():
            time.sleep(0.25)

        self.client.loop_stop()
        self.client.disconnect()

    def stop(self) -> None:
        self.shutdown_event.set()

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if reason_code != 0:
            logging.error("MQTT connect failed with reason_code=%s", reason_code)
            return

        logging.info("Connected to broker at %s:%s", self.mqtt_host, self.mqtt_port)
        client.subscribe(START_REQUEST_TOPIC, qos=1)
        client.subscribe(PRESENCE_TOPIC_FILTER, qos=1)
        client.subscribe(STATE_TOPIC_FILTER, qos=1)
        client.subscribe(ACK_TOPIC_FILTER, qos=1)
        client.subscribe(CALIB_FRAME_TOPIC_FILTER, qos=1)
        client.subscribe(CALIB_DONE_TOPIC_FILTER, qos=1)

        online_payload = {
            "schemaVersion": SCHEMA_VERSION,
            "serverId": self.client_id,
            "status": "online",
            "timestampMs": _now_ms(),
        }
        client.publish(SERVER_STATUS_TOPIC, payload=json.dumps(online_payload), qos=1, retain=True)

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, disconnect_flags: Any, reason_code: Any, properties: Any) -> None:
        if self.shutdown_event.is_set():
            logging.info("Disconnected from MQTT broker.")
            return
        logging.warning("Unexpected MQTT disconnect reason_code=%s", reason_code)

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8")) if msg.payload else {}
        except json.JSONDecodeError:
            logging.warning("Skipping non-JSON payload on topic=%s", msg.topic)
            return

        topic = msg.topic
        if topic == START_REQUEST_TOPIC:
            threading.Thread(target=self._handle_start_request, args=(payload,), daemon=True).start()
            return
        if topic.startswith(f"{TOPIC_PREFIX}/presence/"):
            self._handle_presence(topic, payload)
            return
        if "/capture/state/" in topic:
            self._handle_state(topic, payload)
            return
        if "/capture/ack/" in topic:
            self._handle_ack(topic, payload)
            return
        if "/calibration/frame/" in topic:
            self._handle_calib_frame(topic, payload)
            return
        if "/calibration/done/" in topic:
            self._handle_calib_done(topic, payload)
            return

    def _handle_presence(self, topic: str, payload: Dict[str, Any]) -> None:
        node_id = topic.split("/")[-1]
        record = {
            "payload": payload,
            "updatedMs": _now_ms(),
        }
        with self.presence_lock:
            self.presence[node_id] = record

    def _handle_state(self, topic: str, payload: Dict[str, Any]) -> None:
        parts = topic.split("/")
        if len(parts) < 7:
            return
        group_id = parts[3]
        node_id = parts[-1]
        record = {
            "payload": payload,
            "updatedMs": _now_ms(),
        }
        with self.state_lock:
            self.state[(group_id, node_id)] = record

    def _handle_ack(self, topic: str, payload: Dict[str, Any]) -> None:
        parts = topic.split("/")
        if len(parts) < 7:
            return
        group_id = parts[3]
        node_id = parts[-1]
        command_id = str(payload.get("commandId", ""))
        if not command_id:
            return

        with self.command_lock:
            active = self.active_commands.get(command_id)
        if active is None or active.group_id != group_id:
            return

        with active.lock:
            if node_id not in active.target_nodes:
                return
            if node_id in active.ack_map:
                return

            active.ack_map[node_id] = {
                "receivedMs": _now_ms(),
                "ready": bool(payload.get("ready", False)),
                "latencyMs": payload.get("latencyMs"),
                "payload": payload,
            }

    def _handle_start_request(self, payload: Dict[str, Any]) -> None:
        now_ms = _now_ms()
        schema_version = payload.get("schemaVersion", SCHEMA_VERSION)
        request_id = payload.get("requestId")
        group_id = str(payload.get("groupId", "")).strip()
        capture_config = payload.get("captureConfig", {})
        requested_delay_ms = payload.get("requestedDelayMs")

        if schema_version != SCHEMA_VERSION:
            self._publish_result(
                ok=False,
                reason="unsupported_schema_version",
                request_id=request_id,
                group_id=group_id or None,
                extras={"receivedSchemaVersion": schema_version},
            )
            return

        if not group_id:
            self._publish_result(
                ok=False,
                reason="missing_group_id",
                request_id=request_id,
                group_id=None,
            )
            return

        selected_nodes = self._select_active_nodes(group_id=group_id, now_ms=now_ms)
        if not selected_nodes:
            self._publish_result(
                ok=False,
                reason="no_active_nodes",
                request_id=request_id,
                group_id=group_id,
            )
            return

        delay_ms = self._resolve_delay_ms(requested_delay_ms)
        start_epoch_ms = now_ms + delay_ms
        command_id = f"cmd-{uuid.uuid4().hex[:12]}"
        config_hash = _canonical_json_hash(capture_config)

        active = ActiveCommand(
            command_id=command_id,
            group_id=group_id,
            requested_at_ms=now_ms,
            start_epoch_ms=start_epoch_ms,
            deadline_ms=now_ms + self.ack_timeout_ms,
            request_id=request_id,
            target_nodes=set(selected_nodes),
            capture_config=capture_config,
            config_hash=config_hash,
            ack_map={},
            lock=threading.Lock(),
        )

        with self.command_lock:
            self.active_commands[command_id] = active

        start_topic = f"{TOPIC_PREFIX}/group/{group_id}/capture/start"
        start_payload = {
            "schemaVersion": SCHEMA_VERSION,
            "timestampMs": now_ms,
            "groupId": group_id,
            "commandId": command_id,
            "startEpochMs": start_epoch_ms,
            "configHash": config_hash,
            "captureConfig": capture_config,
            "targetNodeIds": sorted(selected_nodes),
            "expectedNodeCount": len(selected_nodes),
        }
        self.client.publish(start_topic, payload=json.dumps(start_payload), qos=1, retain=False)
        logging.info(
            "Published start command commandId=%s groupId=%s startEpochMs=%d targetNodes=%s",
            command_id,
            group_id,
            start_epoch_ms,
            sorted(selected_nodes),
        )

        # If calibration mode, pre-create a session so frame messages can be matched
        if capture_config.get("calibration", False):
            session = CalibrationSession(
                command_id=command_id,
                group_id=group_id,
                target_nodes=set(selected_nodes),
            )
            with self.calib_lock:
                self.calib_sessions[command_id] = session
            logging.info(
                "Created CalibrationSession commandId=%s targetNodes=%s",
                command_id,
                sorted(selected_nodes),
            )

        self._wait_for_acks_and_publish_result(active)

    def _wait_for_acks_and_publish_result(self, active: ActiveCommand) -> None:
        while _now_ms() < active.deadline_ms and not self.shutdown_event.is_set():
            with active.lock:
                if len(active.ack_map) >= len(active.target_nodes):
                    break
            time.sleep(0.05)

        with active.lock:
            acked_nodes = sorted(active.ack_map.keys())
            ready_nodes: List[str] = []
            failed_nodes: List[str] = []
            ack_details: Dict[str, Any] = {}

            for node_id, ack in active.ack_map.items():
                is_ready = bool(ack.get("ready", False))
                if is_ready:
                    ready_nodes.append(node_id)
                else:
                    failed_nodes.append(node_id)
                ack_details[node_id] = {
                    "ready": is_ready,
                    "latencyMs": ack.get("latencyMs"),
                    "receivedMs": ack.get("receivedMs"),
                }

            missing_nodes = sorted(active.target_nodes - set(acked_nodes))
            success = len(missing_nodes) == 0 and len(failed_nodes) == 0

            result_payload = {
                "schemaVersion": SCHEMA_VERSION,
                "timestampMs": _now_ms(),
                "requestId": active.request_id,
                "groupId": active.group_id,
                "commandId": active.command_id,
                "startEpochMs": active.start_epoch_ms,
                "configHash": active.config_hash,
                "ok": success,
                "reason": "all_nodes_ready" if success else "acks_incomplete_or_not_ready",
                "summary": {
                    "expectedNodeCount": len(active.target_nodes),
                    "ackCount": len(acked_nodes),
                    "readyCount": len(ready_nodes),
                    "notReadyCount": len(failed_nodes),
                    "missingCount": len(missing_nodes),
                },
                "targetNodeIds": sorted(active.target_nodes),
                "ackedNodeIds": acked_nodes,
                "readyNodeIds": sorted(ready_nodes),
                "notReadyNodeIds": sorted(failed_nodes),
                "missingNodeIds": missing_nodes,
                "ackDetails": ack_details,
            }

        self.client.publish(START_RESULT_TOPIC, payload=json.dumps(result_payload), qos=1, retain=False)
        logging.info(
            "Published result commandId=%s ok=%s acked=%d/%d",
            active.command_id,
            result_payload["ok"],
            result_payload["summary"]["ackCount"],
            result_payload["summary"]["expectedNodeCount"],
        )

        with self.command_lock:
            self.active_commands.pop(active.command_id, None)

    def _handle_calib_frame(self, topic: str, payload: Dict[str, Any]) -> None:
        parts = topic.split("/")
        if len(parts) < 7:
            return
        node_id = parts[-1]
        command_id = str(payload.get("commandId", ""))
        frame_num = payload.get("frameNum")
        tracks = payload.get("tracks", [])

        if not command_id:
            return

        # Use the relative frame index (0, 1, 2, ...) as the key.
        # Each node publishes frameNum as the index within its calibration collection
        # window, so the same physical frame has the same key on all nodes regardless
        # of small (<3 ms) wall-clock differences between nodes.
        if frame_num is not None:
            frame_key = int(frame_num)
        else:
            return

        with self.calib_lock:
            session = self.calib_sessions.get(command_id)
            if session is None:
                return

        with session.lock:
            if node_id not in session.frame_data:
                session.frame_data[node_id] = {}
            session.frame_data[node_id][frame_key] = tracks


    def _handle_calib_done(self, topic: str, payload: Dict[str, Any]) -> None:
        parts = topic.split("/")
        if len(parts) < 7:
            return
        node_id = parts[-1]
        command_id = str(payload.get("commandId", ""))
        total_frames = payload.get("totalFrames", 0)

        if not command_id:
            return

        with self.calib_lock:
            session = self.calib_sessions.get(command_id)
            if session is None:
                logging.warning("[CALIB] Done signal for unknown commandId=%s nodeId=%s", command_id, node_id)
                return

        with session.lock:
            session.done_nodes.add(node_id)
            all_done = session.done_nodes >= session.target_nodes
            logging.info(
                "[CALIB] Node done nodeId=%s commandId=%s frames=%d (%d/%d nodes done)",
                node_id,
                command_id,
                total_frames,
                len(session.done_nodes),
                len(session.target_nodes),
            )

        if all_done:
            threading.Thread(target=self._run_calibration, args=(session,), daemon=True).start()

    def _run_calibration(self, session: CalibrationSession) -> None:
        with session.lock:
            frame_data_snapshot = {
                node_id: dict(frames)
                for node_id, frames in session.frame_data.items()
            }
            command_id = session.command_id
            group_id = session.group_id

        logging.info(
            "[CALIB] Running calibration commandId=%s nodes=%s",
            command_id,
            sorted(frame_data_snapshot.keys()),
        )

        node_ids, P_opt, theta_opt, solve_meta = closed_form_calibration(frame_data_snapshot)

        result_topic = f"{TOPIC_PREFIX}/group/{group_id}/calibration/result"
        artifact_payload: Dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "timestampMs": _now_ms(),
            "groupId": group_id,
            "commandId": command_id,
            "snapshotNodeIds": sorted(frame_data_snapshot.keys()),
            "rawFrameDataByNode": frame_data_snapshot,
            "solveMeta": solve_meta if solve_meta is not None else {},
        }

        if node_ids is None:
            failure_reason = (
                solve_meta.get("reason", "calibration_failed")
                if solve_meta else "calibration_failed"
            )
            result_payload: Dict[str, Any] = {
                "schemaVersion": SCHEMA_VERSION,
                "timestampMs": _now_ms(),
                "groupId": group_id,
                "commandId": command_id,
                "ok": False,
                "reason": failure_reason,
                "nodeIds": sorted(frame_data_snapshot.keys()),
            }
            self.client.publish(result_topic, payload=json.dumps(result_payload), qos=1, retain=False)
            logging.warning("[CALIB] Calibration failed commandId=%s reason=%s", command_id, failure_reason)
            artifact_payload.update(
                {
                    "ok": False,
                    "reason": failure_reason,
                }
            )
        else:
            # Serialize complex matrix as list of [real, imag] pairs per cell
            def _serialize_complex(mat: np.ndarray) -> List:
                rows = []
                for row in mat:
                    rows.append([[float(v.real), float(v.imag)] for v in row])
                return rows

            result_payload = {
                "schemaVersion": SCHEMA_VERSION,
                "timestampMs": _now_ms(),
                "groupId": group_id,
                "commandId": command_id,
                "ok": True,
                "reason": "calibration_complete",
                "nodeIds": node_ids,
                "P_opt": _serialize_complex(P_opt),
                "theta_opt": theta_opt.tolist(),
            }
            self.client.publish(result_topic, payload=json.dumps(result_payload), qos=1, retain=False)
            logging.info(
                "[CALIB] Result published commandId=%s nodes=%s topic=%s",
                command_id,
                node_ids,
                result_topic,
            )
            artifact_payload.update(
                {
                    "ok": True,
                    "reason": "calibration_complete",
                    "nodeIds": node_ids,
                    "P_opt": _serialize_complex(P_opt),
                    "theta_opt": theta_opt.tolist(),
                }
            )

        artifact_path = self.calibration_logs_dir / f"calibration_{command_id}_{artifact_payload['timestampMs']}.json"
        try:
            with artifact_path.open("w", encoding="utf-8") as f:
                json.dump(artifact_payload, f, separators=(",", ":"), ensure_ascii=True)
            logging.info("[CALIB] Wrote calibration artifact %s", artifact_path)
        except Exception:
            logging.exception("[CALIB] Failed to write calibration artifact for commandId=%s", command_id)

        with self.calib_lock:
            self.calib_sessions.pop(command_id, None)

    def _select_active_nodes(self, group_id: str, now_ms: int) -> Set[str]:
        active_nodes: Set[str] = set()

        with self.presence_lock:
            
            presence_snapshot = dict(self.presence)
        with self.state_lock:
            state_snapshot = dict(self.state)

        for node_id, record in presence_snapshot.items():
            updated_ms = int(record.get("updatedMs", 0))
            if now_ms - updated_ms > self.presence_stale_ms:
                continue

            payload = record.get("payload", {})
            if payload.get("status") != "online":
                continue
            if str(payload.get("groupId", "")) != group_id:
                continue

            state_record = state_snapshot.get((group_id, node_id))
            if state_record is not None:
                state_updated_ms = int(state_record.get("updatedMs", 0))
                if now_ms - state_updated_ms <= self.state_stale_ms:
                    node_state = str(state_record.get("payload", {}).get("state", ""))
                    if node_state in {"error", "offline"}:
                        continue

            active_nodes.add(node_id)

        return active_nodes

    def _resolve_delay_ms(self, requested_delay_ms: Any) -> int:
        if requested_delay_ms is None:
            delay_ms = self.lead_time_ms
        else:
            try:
                delay_ms = int(requested_delay_ms)
            except (TypeError, ValueError):
                delay_ms = self.lead_time_ms

        if delay_ms < self.min_start_delay_ms:
            return self.min_start_delay_ms
        if delay_ms > self.max_start_delay_ms:
            return self.max_start_delay_ms
        return delay_ms

    def _publish_result(
        self,
        ok: bool,
        reason: str,
        request_id: Optional[str],
        group_id: Optional[str],
        extras: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "timestampMs": _now_ms(),
            "requestId": request_id,
            "groupId": group_id,
            "ok": ok,
            "reason": reason,
        }
        if extras:
            payload.update(extras)

        self.client.publish(START_RESULT_TOPIC, payload=json.dumps(payload), qos=1, retain=False)
        logging.info("Published request result ok=%s reason=%s groupId=%s", ok, reason, group_id)


def main() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    controller = ServerController()

    def handle_signal(sig: int, frame: Any) -> None:
        logging.info("Signal %s received, shutting down.", sig)
        controller.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        controller.run()
    except KeyboardInterrupt:
        controller.stop()
    except Exception:
        logging.exception("Fatal server controller error")
        raise


if __name__ == "__main__":
    main()
