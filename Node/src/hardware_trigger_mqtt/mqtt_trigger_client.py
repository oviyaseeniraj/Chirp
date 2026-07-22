#!/usr/bin/env python3
"""MQTT control client for Orin trigger worker – time-calibration decoupled.

Implements the three-state machine:
  IDLE → LIVE (on time-sync tick, calibration=false)
  LIVE → LIVE (re-align on each time-sync tick)
  LIVE → CALIBRATION (on calibration tick, calibration=true)
  CALIBRATION → LIVE (after burst complete)

"""

from __future__ import annotations

# MODULE-LEVEL diagnostic — write before remaining imports.
import os as _os
_os.write(2, b"TRIGGER_CLIENT_MODULE_LOADED\n")

import json

import json
import logging
import os
import select
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import paho.mqtt.client as mqtt
from command_cache import CommandCache


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        logging.warning(
            "Invalid integer for %s=%r; using default=%d", name, value, default
        )
        return default


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class WorkerConfig:
    binary_path: str
    pulse_period_ms: Optional[int]
    max_pulses: Optional[int]
    cpu_core: Optional[int]


class NodeTriggerClient:
    # ── state constants ──────────────────────────────────────────────
    STATE_IDLE = "idle"
    STATE_LIVE = "live"
    STATE_CALIBRATION = "calibration"
    STATE_ERROR = "error"
    STATE_OFFLINE = "offline"

    def __init__(self) -> None:
        self.schema_version = _env_int("CHIRP_SCHEMA_VERSION", 1)
        self.topic_prefix = os.getenv("CHIRP_TOPIC_PREFIX", "chirp/v1")

        self.node_id = os.getenv("NODE_ID", socket.gethostname())
        self.group_id = os.getenv("GROUP_ID", "default")
        self.client_id = os.getenv("MQTT_CLIENT_ID", f"radar-{self.node_id}")

        self.mqtt_host = os.getenv("MQTT_HOST", "127.0.0.1")
        print("MQTT TRIGGER")
        print(self.mqtt_host)
        self.mqtt_port = _env_int("MQTT_PORT", 1883)
        self.mqtt_user = os.getenv("MQTT_USERNAME", self.node_id)
        self.mqtt_pass = os.getenv("MQTT_PASSWORD", "")
        self.keepalive_sec = _env_int("MQTT_KEEPALIVE_SEC", 30)
        self.presence_heartbeat_ms = _env_int("PRESENCE_HEARTBEAT_MS", 2000)

        self.command_cache_ttl_ms = _env_int(
            "COMMAND_CACHE_TTL_MS", 5 * 60 * 1000
        )
        self.command_replay_max_age_ms = _env_int(
            "COMMAND_REPLAY_MAX_AGE_MS", 30 * 1000
        )
        self.command_start_late_grace_ms = _env_int(
            "COMMAND_START_LATE_GRACE_MS", 250
        )
        self.command_start_future_max_skew_ms = _env_int(
            "COMMAND_START_FUTURE_MAX_SKEW_MS",
            10 * 60 * 1000,
        )

        # ── topic strings ────────────────────────────────────────────
        self.start_topic = f"{self.topic_prefix}/group/{self.group_id}/capture/start"
        self.calib_result_topic = f"{self.topic_prefix}/group/{self.group_id}/calibration/result"
        self.calib_done_topic = f"{self.topic_prefix}/group/{self.group_id}/calibration/done/{self.node_id}"
        self.node_cmd_topic = f"{self.topic_prefix}/group/{self.group_id}/node/{self.node_id}/command"
        self.presence_topic = f"{self.topic_prefix}/presence/{self.node_id}"
        self.state_topic = f"{self.topic_prefix}/group/{self.group_id}/capture/state/{self.node_id}"
        self.ack_topic = f"{self.topic_prefix}/group/{self.group_id}/capture/ack/{self.node_id}"

        default_worker = Path(__file__).resolve().parent / "trigger_worker"
        self.worker_cfg = WorkerConfig(
            binary_path=os.getenv("TRIGGER_WORKER_PATH", str(default_worker)),
            pulse_period_ms=_env_int("TRIGGER_PULSE_PERIOD_MS", 100)
            if os.getenv("TRIGGER_PULSE_PERIOD_MS")
            else None,
            max_pulses=_env_int("TRIGGER_MAX_PULSES", -1)
            if os.getenv("TRIGGER_MAX_PULSES")
            else None,
            cpu_core=_env_int("TRIGGER_CPU_CORE", 5)
            if os.getenv("TRIGGER_CPU_CORE")
            else None,
        )

        # ── runtime state ────────────────────────────────────────────
        self.shutdown_event = threading.Event()
        self.presence_thread: Optional[threading.Thread] = None
        self.worker_lock = threading.Lock()
        self.worker_process: Optional[subprocess.Popen[str]] = None
        self._worker_watcher: Optional[threading.Thread] = None

        self.last_command_id: Optional[str] = None
        self.current_state = self.STATE_IDLE

        # Time-sync state (tracked separately from calibration commands)
        self._timesync_start_epoch_ms: Optional[int] = None
        self._timesync_command_id: Optional[str] = None

        # Last calibration matrix received (applied to live frames)
        self._last_calibration_result: Optional[Dict[str, Any]] = None

        self.command_cache = CommandCache(ttl_ms=self.command_cache_ttl_ms)

        # ── MQTT client ──────────────────────────────────────────────
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            clean_session=False,
        )
        if self.mqtt_user:
            self.client.username_pw_set(self.mqtt_user, self.mqtt_pass)

        offline_presence = self._presence_payload(status="offline")
        self.client.will_set(
            self.presence_topic,
            payload=json.dumps(offline_presence),
            qos=1,
            retain=True,
        )

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    # ── payload helpers ──────────────────────────────────────────────

    def _presence_payload(self, status: str) -> Dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "timestampMs": _now_ms(),
            "nodeId": self.node_id,
            "groupId": self.group_id,
            "role": "radar",
            "status": status,
        }

    def _state_payload(
        self,
        state: str,
        *,
        command_id: Optional[str] = None,
        error: Optional[str] = None,
        start_epoch_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "schemaVersion": self.schema_version,
            "timestampMs": _now_ms(),
            "nodeId": self.node_id,
            "groupId": self.group_id,
            "state": state,
            "lastCommandId": command_id or self.last_command_id,
        }
        if error:
            payload["error"] = error
        if start_epoch_ms is not None:
            payload["startEpochMs"] = start_epoch_ms
        return payload

    def _publish_presence(self, status: str) -> None:
        self.client.publish(
            self.presence_topic,
            payload=json.dumps(self._presence_payload(status)),
            qos=1,
            retain=True,
        )

    def _publish_state(
        self,
        state: str,
        *,
        command_id: Optional[str] = None,
        error: Optional[str] = None,
        start_epoch_ms: Optional[int] = None,
    ) -> None:
        self.current_state = state
        self.client.publish(
            self.state_topic,
            payload=json.dumps(
                self._state_payload(
                    state,
                    command_id=command_id,
                    error=error,
                    start_epoch_ms=start_epoch_ms,
                )
            ),
            qos=1,
            retain=True,
        )

    def _publish_ack(
        self,
        *,
        command_id: str,
        ready: bool,
        start_epoch_ms: Optional[int],
        latency_ms: Optional[int],
        reason: Optional[str] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "schemaVersion": self.schema_version,
            "timestampMs": _now_ms(),
            "groupId": self.group_id,
            "nodeId": self.node_id,
            "commandId": command_id,
            "ready": ready,
            "latencyMs": latency_ms,
        }
        if start_epoch_ms is not None:
            payload["startEpochMs"] = start_epoch_ms
        if reason:
            payload["reason"] = reason

        self.client.publish(
            self.ack_topic, payload=json.dumps(payload), qos=1, retain=False
        )

    # ── MQTT callbacks ───────────────────────────────────────────────

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        if reason_code != 0:
            logging.error("MQTT connect failed with reason_code=%s", reason_code)
            return

        logging.info("Connected to broker at %s:%d", self.mqtt_host, self.mqtt_port)
        client.subscribe(self.start_topic, qos=1)
        client.subscribe(self.calib_result_topic, qos=1)
        client.subscribe(self.calib_done_topic, qos=1)
        client.subscribe(self.node_cmd_topic, qos=1)

        # Publish presence + state as per new-node-join flow
        self._publish_presence(status="online")
        self._publish_state(self.STATE_IDLE)
        logging.info(
            "Subscribed to: %s, %s, %s, %s",
            self.start_topic,
            self.calib_result_topic,
            self.calib_done_topic,
            self.node_cmd_topic,
        )

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        if self.shutdown_event.is_set():
            logging.info("Disconnected from MQTT broker.")
            return
        logging.warning("Unexpected MQTT disconnect reason_code=%s", reason_code)

    def _on_message(
        self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage
    ) -> None:
        topic = msg.topic

        try:
            payload = json.loads(msg.payload.decode("utf-8")) if msg.payload else {}
        except json.JSONDecodeError:
            logging.warning("Ignoring non-JSON payload on topic=%s", topic)
            return

        if topic == self.start_topic:
            self._handle_start(payload)
        elif topic == self.calib_result_topic:
            self._handle_calibration_result(payload)
        elif topic == self.calib_done_topic:
            self._handle_calibration_done(payload)
        elif topic == self.node_cmd_topic:
            self._handle_node_command(payload)

    # ── message handlers ─────────────────────────────────────────────

    def _validate_start_payload(
        self, payload: Dict[str, Any], t0: int
    ) -> Optional[Dict[str, Any]]:
        """Shared validation for all capture/start messages.

        Returns a dict with validated fields on success, or calls
        _publish_ack/_publish_state with an error and returns None.
        """
        command_id = str(payload.get("commandId", "")).strip()
        group_id = str(payload.get("groupId", "")).strip()
        schema_version_raw = payload.get("schemaVersion", self.schema_version)
        start_epoch_ms = payload.get("startEpochMs")
        target_node_ids = payload.get("targetNodeIds")
        timestamp_ms_raw = payload.get("timestampMs")

        try:
            schema_version = int(schema_version_raw)
        except (TypeError, ValueError):
            self._publish_ack(
                command_id=command_id or "missing-command-id",
                ready=False,
                start_epoch_ms=None,
                latency_ms=_now_ms() - t0,
                reason="invalid_schema_version",
            )
            return None

        if not command_id:
            logging.warning("Ignoring start without commandId")
            return None

        if group_id != self.group_id:
            logging.info("Ignoring commandId=%s for group=%s", command_id, group_id)
            return None

        if schema_version != self.schema_version:
            self._publish_ack(
                command_id=command_id,
                ready=False,
                start_epoch_ms=None,
                latency_ms=_now_ms() - t0,
                reason="unsupported_schema_version",
            )
            return None

        if self.command_cache.contains(command_id):
            self._publish_ack(
                command_id=command_id,
                ready=True,
                start_epoch_ms=None,
                latency_ms=_now_ms() - t0,
                reason="duplicate_command_ignored",
            )
            logging.info("Duplicate command ignored commandId=%s", command_id)
            return None

        if target_node_ids and self.node_id not in [str(v) for v in target_node_ids]:
            logging.info(
                "Ignoring commandId=%s not targeted to nodeId=%s",
                command_id,
                self.node_id,
            )
            return None

        try:
            start_epoch_ms_int = int(start_epoch_ms)
        except (TypeError, ValueError):
            self._publish_ack(
                command_id=command_id,
                ready=False,
                start_epoch_ms=None,
                latency_ms=_now_ms() - t0,
                reason="invalid_start_epoch_ms",
            )
            self._publish_state(
                self.STATE_ERROR, command_id=command_id, error="invalid_start_epoch_ms"
            )
            return None

        now_ms = _now_ms()
        if start_epoch_ms_int < now_ms - self.command_start_late_grace_ms:
            # ⚠ For time-sync ticks that arrive regularly, we relax the staleness
            # check so that a just-slightly-late tick still gets accepted. The
            # timesync service publishes every 10 s; network jitter may cause
            # the payload to arrive a few hundred ms "late" relative to the
            # startEpochMs it contains. Accept it as long as it's within the
            # extended tolerance window for timesync ticks. For calibration
            # commands we keep the strict grace.
            capture_cfg = payload.get("captureConfig", {}) or {}
            is_calibration = bool(capture_cfg.get("calibration", False))

            if is_calibration:
                self._publish_ack(
                    command_id=command_id,
                    ready=False,
                    start_epoch_ms=start_epoch_ms_int,
                    latency_ms=_now_ms() - t0,
                    reason="stale_start_epoch_ms",
                )
                logging.warning(
                    "Rejected stale calibration command commandId=%s startEpochMs=%d nowMs=%d",
                    command_id,
                    start_epoch_ms_int,
                    now_ms,
                )
                return None
            else:
                # Time-sync tick: tolerate slightly stale epochs.
                timesync_late_grace_ms = _env_int(
                    "TIMESYNC_LATE_GRACE_MS",
                    self.command_start_late_grace_ms + 5000,
                )
                if start_epoch_ms_int < now_ms - timesync_late_grace_ms:
                    self._publish_ack(
                        command_id=command_id,
                        ready=False,
                        start_epoch_ms=start_epoch_ms_int,
                        latency_ms=_now_ms() - t0,
                        reason="stale_timesync_epoch",
                    )
                    logging.warning(
                        "Rejected stale time-sync commandId=%s startEpochMs=%d nowMs=%d",
                        command_id,
                        start_epoch_ms_int,
                        now_ms,
                    )
                    return None

        if start_epoch_ms_int > now_ms + self.command_start_future_max_skew_ms:
            self._publish_ack(
                command_id=command_id,
                ready=False,
                start_epoch_ms=start_epoch_ms_int,
                latency_ms=_now_ms() - t0,
                reason="start_epoch_too_far_in_future",
            )
            logging.warning(
                "Rejected far-future command commandId=%s startEpochMs=%d nowMs=%d",
                command_id,
                start_epoch_ms_int,
                now_ms,
            )
            return None

        if timestamp_ms_raw is not None:
            try:
                timestamp_ms = int(timestamp_ms_raw)
            except (TypeError, ValueError):
                timestamp_ms = None
            if (
                timestamp_ms is not None
                and timestamp_ms + self.command_replay_max_age_ms < now_ms
            ):
                self._publish_ack(
                    command_id=command_id,
                    ready=False,
                    start_epoch_ms=start_epoch_ms_int,
                    latency_ms=_now_ms() - t0,
                    reason="stale_command_timestamp",
                )
                logging.warning(
                    "Rejected replayed command commandId=%s timestampMs=%d nowMs=%d",
                    command_id,
                    timestamp_ms,
                    now_ms,
                )
                return None

        return {
            "command_id": command_id,
            "start_epoch_ms": start_epoch_ms_int,
            "capture_config": (payload.get("captureConfig", {}) or {}),
        }

    def _handle_start(self, payload: Dict[str, Any]) -> None:
        """Route capture/start to time-sync or calibration handler."""
        t0 = _now_ms()

        validated = self._validate_start_payload(payload, t0)
        if validated is None:
            return

        command_id: str = validated["command_id"]
        start_epoch_ms: int = validated["start_epoch_ms"]
        capture_config: Dict[str, Any] = validated["capture_config"]
        is_calibration = bool(capture_config.get("calibration", False))

        if is_calibration:
            self._handle_calibration_start(command_id, start_epoch_ms, capture_config, t0)
        else:
            self._handle_timesync_tick(command_id, start_epoch_ms, t0)

    # ── time-sync tick (calibration=false) ───────────────────────────

    def _handle_timesync_tick(
        self, command_id: str, start_epoch_ms: int, t0: int
    ) -> None:
        """Handle a periodic time-synchronisation tick.

        IDLE → LIVE:   start the hardware trigger worker.
        LIVE → LIVE:   record the tick, keep the existing worker running.
        CALIBRATION:   record the tick for later but do NOT interrupt the burst.
        """
        logging.info(
            "Time-sync tick commandId=%s startEpochMs=%d (current state=%s)",
            command_id,
            start_epoch_ms,
            self.current_state,
        )

        # Always record the latest time-sync reference
        self._timesync_start_epoch_ms = start_epoch_ms
        self._timesync_command_id = command_id
        self.last_command_id = command_id
        self.command_cache.remember(command_id)

        if self.current_state == self.STATE_CALIBRATION:
            self._publish_ack(
                command_id=command_id,
                ready=True,
                start_epoch_ms=start_epoch_ms,
                latency_ms=_now_ms() - t0,
                reason="timesync_recorded_during_calibration",
            )
            logging.info(
                "Timesync tick recorded (node in calibration); will apply after burst"
            )
            return

        if self.current_state == self.STATE_LIVE:
            # Already capturing — the existing worker stays running.
            # The tick is for other nodes joining the group to align.
            self._publish_ack(
                command_id=command_id,
                ready=True,
                start_epoch_ms=start_epoch_ms,
                latency_ms=_now_ms() - t0,
            )
            logging.info("Timesync tick acknowledged (already live)")
            return

        if self.current_state == self.STATE_ERROR:
            logging.info("Accepting time-sync tick to recover from error state")
            self.current_state = self.STATE_IDLE

        # ── IDLE → LIVE: start the first worker ────────────────────
        with self.worker_lock:
            if self.worker_process and self.worker_process.poll() is None:
                logging.info("Terminating stale worker pid=%s", self.worker_process.pid)
                self.worker_process.terminate()
                try:
                    self.worker_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.worker_process.kill()
                    self.worker_process.wait(timeout=2)
                self.worker_process = None

            argv = self._build_worker_argv(start_epoch_ms, max_pulses=None)
            try:
                self.worker_process = subprocess.Popen(
                    argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                )
            except Exception as exc:
                self._publish_ack(
                    command_id=command_id,
                    ready=False,
                    start_epoch_ms=start_epoch_ms,
                    latency_ms=_now_ms() - t0,
                    reason="worker_launch_failed",
                )
                self._publish_state(
                    self.STATE_ERROR,
                    command_id=command_id,
                    error=f"worker_launch_failed:{exc}",
                )
                logging.exception("Failed to launch trigger worker commandId=%s", command_id)
                return

        self._publish_ack(
            command_id=command_id,
            ready=True,
            start_epoch_ms=start_epoch_ms,
            latency_ms=_now_ms() - t0,
        )
        logging.info(
            "Live capture launch commandId=%s startEpochMs=%d workerPid=%s",
            command_id,
            start_epoch_ms,
            self.worker_process.pid if self.worker_process else None,
        )

        self._start_worker_watcher(
            self.worker_process,
            command_id=command_id,
            start_epoch_ms=start_epoch_ms,
        )

    # ── calibration start (calibration=true) ─────────────────────────

    def _handle_calibration_start(
        self,
        command_id: str,
        start_epoch_ms: int,
        capture_config: Dict[str, Any],
        t0: int,
    ) -> None:
        """Handle a calibration run command.

        The hardware trigger worker keeps running uninterrupted.
        Only the state changes — the calibration_mqtt_process (separate
        pipeline process) collects N frames of centroid data from the
        existing pipeline and publishes them to the calibration topics.
        """
        calibration_frames = int(capture_config.get("calibrationFrames", 150))
        logging.info(
            "Calibration command commandId=%s frames=%d (current state=%s) — worker stays running",
            command_id,
            calibration_frames,
            self.current_state,
        )

        self.last_command_id = command_id
        self.command_cache.remember(command_id)

        self._publish_state(
            self.STATE_CALIBRATION,
            command_id=command_id,
            start_epoch_ms=start_epoch_ms,
        )
        self._publish_ack(
            command_id=command_id,
            ready=True,
            start_epoch_ms=start_epoch_ms,
            latency_ms=_now_ms() - t0,
        )

    def _handle_calibration_done(self, payload: Dict[str, Any]) -> None:
        """calibration/done published by calibration_mqtt_process —
        the burst is complete, transition back to LIVE."""
        logging.info(
            "Calibration done received commandId=%s totalFrames=%s — back to live",
            payload.get("commandId"),
            payload.get("totalFrames"),
        )
        if self.current_state == self.STATE_CALIBRATION:
            self._publish_state(self.STATE_LIVE)
        else:
            logging.debug(
                "calibration/done received but not in calibration state (state=%s)",
                self.current_state,
            )

    # ── calibration result ───────────────────────────────────────────

    def _handle_calibration_result(self, payload: Dict[str, Any]) -> None:
        """Store the latest calibration matrix for application to live frames."""
        target_ids = payload.get("targetNodeIds")
        if target_ids and self.node_id not in [str(t) for t in target_ids]:
            return

        self._last_calibration_result = payload
        logging.info(
            "Calibration result received commandId=%s; stored for live-frame application",
            payload.get("commandId"),
        )

    # ── node command (debug/dashboard) ────────────────────────────────

    def _handle_node_command(self, payload: Dict[str, Any]) -> None:
        """Handle dashboard debug commands sent to this specific node."""
        command = str(payload.get("command", payload.get("action", ""))).strip()
        target = str(payload.get("nodeId", "")).strip()

        if target and target != self.node_id:
            return

        if not command:
            return  # empty command from dashboard lifecycle messages; ignore silently

        # Commands handled by node_launcher — acknowledge but don't act.
        if command in ("start_pipeline", "stop_pipeline", "start_radar", "reset_radar"):
            logging.debug("Ignoring launcher command: %s", command)
            return

        logging.info("Node command received: %s", command)

        if command == "stop":
            with self.worker_lock:
                if self.worker_process and self.worker_process.poll() is None:
                    logging.info("Stop command: terminating worker pid=%s", self.worker_process.pid)
                    self.worker_process.terminate()
                    try:
                        self.worker_process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self.worker_process.kill()
                        self.worker_process.wait(timeout=2)
                    self.worker_process = None
            self._publish_state(self.STATE_IDLE, command_id=self.last_command_id)
        elif command == "status":
            self._publish_state(self.current_state, command_id=self.last_command_id)
        else:
            logging.info("Unknown node command: %s", command)

    # ── worker lifecycle ─────────────────────────────────────────────

    def _build_worker_argv(
        self, start_epoch_ms: int, max_pulses: Optional[int]
    ) -> List[str]:
        """Build the argv list for the trigger_worker subprocess."""
        argv: List[str] = [
            self.worker_cfg.binary_path,
            "--start-epoch-ms",
            str(start_epoch_ms),
        ]
        if self.worker_cfg.pulse_period_ms is not None:
            argv += ["--pulse-period-ms", str(self.worker_cfg.pulse_period_ms)]
        if max_pulses is not None:
            argv += ["--max-pulses", str(max_pulses)]
        elif self.worker_cfg.max_pulses is not None and self.worker_cfg.max_pulses > 0:
            argv += ["--max-pulses", str(self.worker_cfg.max_pulses)]
        else:
            # Live capture (no max_pulses) — suppress per-pulse verbose output.
            argv += ["--quiet"]
        if self.worker_cfg.cpu_core is not None:
            argv += ["--cpu-core", str(self.worker_cfg.cpu_core)]
        return argv

    def _start_worker_watcher(
        self,
        process: subprocess.Popen[str],
        *,
        command_id: str,
        start_epoch_ms: int,
    ) -> None:
        """Launch a daemon thread that reads the live worker's stdout."""
        if self._worker_watcher and self._worker_watcher.is_alive():
            pass

        self._worker_watcher = threading.Thread(
            target=self._worker_stdout_reader,
            args=(process, command_id, start_epoch_ms),
            daemon=True,
        )
        self._worker_watcher.start()

    def _worker_stdout_reader(
        self,
        process: subprocess.Popen[str],
        command_id: str,
        start_epoch_ms: int,
    ) -> None:
        """Read STATUS: lines from the live worker; poll with select so we
        detect worker death within ~1 second even when stdout is quiet."""
        pulse_count = 0
        try:
            assert process.stdout is not None
            buf = ""
            while True:
                # Check if the process is still alive.
                if process.poll() is not None:
                    # Drain any remaining data before breaking.
                    try:
                        leftover = process.stdout.read()
                        if leftover:
                            buf += leftover
                    except Exception:
                        pass
                    break

                # Wait for data with a 1-second timeout.
                try:
                    ready, _, _ = select.select([process.stdout], [], [], 1.0)
                except (ValueError, OSError):
                    break

                if ready:
                    chunk = process.stdout.readline()
                    if not chunk:
                        break
                    buf += chunk

                # Process complete lines from the buffer.
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.rstrip("\r")
                    if not line.startswith("STATUS:"):
                        logging.debug("worker stdout: %s", line)
                        continue

                    rest = line[len("STATUS:"):].strip()
                    parts = rest.split(None, 1)
                    keyword = parts[0] if parts else ""
                    detail = parts[1] if len(parts) > 1 else ""

                    if keyword == "ARMED":
                        logging.info("Worker armed: %s", detail)
                        self._publish_state(
                            self.STATE_LIVE,
                            command_id=command_id,
                            start_epoch_ms=start_epoch_ms,
                        )

                    elif keyword == "STARTED":
                        started_epoch_ms: Optional[int] = None
                        for token in detail.split():
                            if token.startswith("epochMs="):
                                try:
                                    started_epoch_ms = int(token.split("=", 1)[1])
                                except ValueError:
                                    pass
                        logging.info(
                            "Worker first pulse fired: %s (epochMs=%s)",
                            detail,
                            started_epoch_ms,
                        )
                        pulse_count = 1

                    elif keyword == "PULSE":
                        pulse_count += 1

                    elif keyword == "DONE":
                        logging.info("Worker done: %s", detail)
                        total_pulses = 0
                        for token in detail.split():
                            if token.startswith("totalPulses="):
                                try:
                                    total_pulses = int(token.split("=", 1)[1])
                                except ValueError:
                                    pass
                        logging.info("Worker exited totalPulses=%d", total_pulses)
                        break

                    else:
                        logging.debug("Unknown worker status: %s", keyword)

        except Exception:
            logging.exception("Error reading worker stdout")

        # Wait for process to fully terminate
        exit_code = process.wait()
        with self.worker_lock:
            was_active = (self.worker_process is process)
            if was_active:
                self.worker_process = None

        if self.shutdown_event.is_set():
            return

        # If a new worker was launched before we finished (e.g. time-sync
        # re-align), this watcher is obsolete — don't publish any state.
        if not was_active:
            logging.debug("Worker watcher superseded — skipping state")
            return

        # Live worker exited (unexpected — it should run forever).
        if exit_code == 0:
            logging.warning("Live worker exited cleanly (unexpected); going to idle")
            self._publish_state(self.STATE_IDLE)
        else:
            logging.warning(
                "Live worker exited with error code=%d; going to error state",
                exit_code,
            )
            self._publish_state(
                self.STATE_ERROR,
                error=f"live_worker_exit_{exit_code}",
            )

    # ── presence loop ────────────────────────────────────────────────

    def _presence_loop(self) -> None:
        while not self.shutdown_event.is_set():
            self._publish_presence(status="online")
            self.shutdown_event.wait(self.presence_heartbeat_ms / 1000.0)

    # ── top-level run / stop ─────────────────────────────────────────

    def run(self) -> None:
        self.client.connect(
            self.mqtt_host, self.mqtt_port, keepalive=self.keepalive_sec
        )
        self.client.loop_start()

        self.presence_thread = threading.Thread(target=self._presence_loop, daemon=True)
        self.presence_thread.start()

        logging.info(
            "Node MQTT trigger client running nodeId=%s groupId=%s clientId=%s startTopic=%s",
            self.node_id,
            self.group_id,
            self.client_id,
            self.start_topic,
        )

        while not self.shutdown_event.is_set():
            time.sleep(0.25)

        self.stop()

    def stop(self) -> None:
        if self.shutdown_event.is_set():
            return

        self.shutdown_event.set()
        with self.worker_lock:
            if self.worker_process and self.worker_process.poll() is None:
                self.worker_process.terminate()
                try:
                    self.worker_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.worker_process.kill()
                    self.worker_process.wait(timeout=2)
            self.worker_process = None

        self._publish_state(self.STATE_OFFLINE, command_id=self.last_command_id)
        self._publish_presence(status="offline")
        self.client.loop_stop()
        self.client.disconnect()


def main() -> None:
    # Write to stderr immediately (unbuffered OS-level write) so systemd
    # journal captures this even if the script crashes before logging is init'd.
    os.write(2, f"mqtt_trigger_client starting  pid={os.getpid()}\n".encode())

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    node_client = NodeTriggerClient()

    def _signal_handler(sig: int, frame: Any) -> None:
        logging.info("Signal %s received, shutting down.", sig)
        node_client.stop()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        node_client.run()
    except KeyboardInterrupt:
        node_client.stop()
    except Exception:
        logging.exception("Fatal node MQTT trigger client error")
        raise


if __name__ == "__main__":
    main()
