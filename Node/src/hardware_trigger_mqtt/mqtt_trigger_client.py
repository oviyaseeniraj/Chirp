#!/usr/bin/env python3
"""Phase 2/3 MQTT control client for Orin trigger worker."""

from __future__ import annotations

import json
import logging
import os
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
        )  # stores how long a commandId lives in the CommandCache
        self.command_replay_max_age_ms = _env_int(
            "COMMAND_REPLAY_MAX_AGE_MS", 30 * 1000
        )  # checks payload timestampMs and rejects message if it is too old
        self.command_start_late_grace_ms = _env_int(
            "COMMAND_START_LATE_GRACE_MS", 250
        )  # allow slight lateness from network jitter when receiving start/capture message
        self.command_start_future_max_skew_ms = _env_int(  # rejects startEpochMs that is unrealistic / too far into the future
            "COMMAND_START_FUTURE_MAX_SKEW_MS",
            10 * 60 * 1000,
        )

        self.start_topic = f"{self.topic_prefix}/group/{self.group_id}/capture/start"  # subscribed topic
        self.presence_topic = (
            f"{self.topic_prefix}/presence/{self.node_id}"  # published topic
        )
        self.state_topic = f"{self.topic_prefix}/group/{self.group_id}/capture/state/{self.node_id}"  # published topic
        self.ack_topic = f"{self.topic_prefix}/group/{self.group_id}/capture/ack/{self.node_id}"  # published topic

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

        self.shutdown_event = threading.Event()
        self.presence_thread: Optional[threading.Thread] = None
        self.worker_lock = threading.Lock()
        self.worker_process: Optional[subprocess.Popen[str]] = None
        self.last_command_id: Optional[str] = None
        self.current_state = "idle"
        self.command_cache = CommandCache(ttl_ms=self.command_cache_ttl_ms)

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            clean_session=False,
        )
        if self.mqtt_user:
            self.client.username_pw_set(self.mqtt_user, self.mqtt_pass)

        # this is the message that will display in the presence topic of this node when the node goes offline
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
        latency_ms: Optional[
            int
        ],  # computes the time between laptop start request & time to produce an ACK
        reason: Optional[str] = None,  # reason for why this node is NOT ready
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

    # upon connecting to the MQTT broker, subscribe to the capture/start topic & publish state/presence
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
        self._publish_presence(status="online")
        self._publish_state("idle")

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
        if msg.topic != self.start_topic:
            return

        try:
            # json.loads() parses a JSON formatted string into Python objects
            payload = json.loads(msg.payload.decode("utf-8")) if msg.payload else {}
        except json.JSONDecodeError:
            logging.warning("Ignoring non-JSON start payload on topic=%s", msg.topic)
            return

        self._handle_start(payload)

    def _handle_start(self, payload: Dict[str, Any]) -> None:
        t0 = _now_ms()
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
            return

        if not command_id:
            logging.warning("Ignoring start without commandId")
            return

        if group_id != self.group_id:
            logging.info("Ignoring commandId=%s for group=%s", command_id, group_id)
            return

        if schema_version != self.schema_version:
            self._publish_ack(
                command_id=command_id,
                ready=False,
                start_epoch_ms=None,
                latency_ms=_now_ms() - t0,
                reason="unsupported_schema_version",
            )
            return

        if self.command_cache.contains(command_id):
            # QoS1 redelivery can replay the same command payload; ignore execution.
            self._publish_ack(
                command_id=command_id,
                ready=True,
                start_epoch_ms=None,
                latency_ms=_now_ms() - t0,
                reason="duplicate_command_ignored",
            )
            logging.info("Duplicate command ignored commandId=%s", command_id)
            return

        if target_node_ids and self.node_id not in [str(v) for v in target_node_ids]:
            logging.info(
                "Ignoring commandId=%s not targeted to nodeId=%s",
                command_id,
                self.node_id,
            )
            return

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
                "error", command_id=command_id, error="invalid_start_epoch_ms"
            )
            return

        now_ms = _now_ms()
        if start_epoch_ms_int < now_ms - self.command_start_late_grace_ms:
            self._publish_ack(
                command_id=command_id,
                ready=False,
                start_epoch_ms=start_epoch_ms_int,
                latency_ms=_now_ms() - t0,
                reason="stale_start_epoch_ms",
            )
            logging.warning(
                "Rejected stale command commandId=%s startEpochMs=%d nowMs=%d",
                command_id,
                start_epoch_ms_int,
                now_ms,
            )
            return

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
            return

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
                return

        with self.worker_lock:
            if (
                self.worker_process and self.worker_process.poll() is None
            ):  # process is still running
                self._publish_ack(
                    command_id=command_id,
                    ready=False,
                    start_epoch_ms=start_epoch_ms_int,
                    latency_ms=_now_ms() - t0,
                    reason="worker_busy",
                )
                logging.warning("Worker busy; rejected commandId=%s", command_id)
                return

            # argv contains the terminal command to run the trigger_worker executable; it's used to run as a subprocess under this mqtt_trigger_client.py parent process
            argv: List[str] = [
                self.worker_cfg.binary_path,
                "--start-epoch-ms",
                str(start_epoch_ms_int),
            ]
            if self.worker_cfg.pulse_period_ms is not None:
                argv += ["--pulse-period-ms", str(self.worker_cfg.pulse_period_ms)]
            if self.worker_cfg.max_pulses is not None:
                argv += ["--max-pulses", str(self.worker_cfg.max_pulses)]
            if self.worker_cfg.cpu_core is not None:
                argv += ["--cpu-core", str(self.worker_cfg.cpu_core)]

            try:
                self.worker_process = subprocess.Popen(argv)
            except Exception as exc:
                self._publish_ack(
                    command_id=command_id,
                    ready=False,
                    start_epoch_ms=start_epoch_ms_int,
                    latency_ms=_now_ms() - t0,
                    reason="worker_launch_failed",
                )
                self._publish_state(
                    "error", command_id=command_id, error=f"worker_launch_failed:{exc}"
                )
                logging.exception(
                    "Failed to launch trigger worker commandId=%s", command_id
                )
                return

            self.last_command_id = command_id
            self.command_cache.remember(command_id)
            self._publish_state(
                "arming",
                command_id=command_id,
                start_epoch_ms=start_epoch_ms_int,
            )
            self._publish_ack(
                command_id=command_id,
                ready=True,
                start_epoch_ms=start_epoch_ms_int,
                latency_ms=_now_ms() - t0,
            )
            logging.info(
                "Accepted commandId=%s startEpochMs=%d workerPid=%s",
                command_id,
                start_epoch_ms_int,
                self.worker_process.pid if self.worker_process else None,
            )

            threading.Thread(
                target=self._watch_worker,
                args=(command_id, start_epoch_ms_int, self.worker_process),
                daemon=True,
            ).start()

    def _watch_worker(
        self,
        command_id: str,
        start_epoch_ms: int,
        process: subprocess.Popen[str],
    ) -> None:
        # Wait until close to start epoch before switching to "capturing" so dashboards
        # see a deterministic arming -> capturing transition.
        sleep_ms = max(0, start_epoch_ms - _now_ms())
        if sleep_ms > 0:
            time.sleep(sleep_ms / 1000.0)

        with self.worker_lock:
            if self.worker_process is process and process.poll() is None:
                self._publish_state(
                    "capturing",
                    command_id=command_id,
                    start_epoch_ms=start_epoch_ms,
                )

        exit_code = process.wait()
        with self.worker_lock:
            if self.worker_process is process:
                self.worker_process = None

        if exit_code == 0:
            self._publish_state("idle", command_id=command_id)
            logging.info("Worker exited cleanly commandId=%s", command_id)
        else:
            self._publish_state(
                "error",
                command_id=command_id,
                error=f"worker_exit_{exit_code}",
            )
            logging.warning(
                "Worker exited with error code=%d commandId=%s", exit_code, command_id
            )

    def _presence_loop(self) -> None:
        while not self.shutdown_event.is_set():
            self._publish_presence(status="online")
            self.shutdown_event.wait(
                self.presence_heartbeat_ms / 1000.0
            )  # sleep presence "heartbeat" for 2 seconds

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

        # main thread runs every 0.25 seconds to run the mqtt client (from client.loop_start()) and presence_thread
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

        self._publish_state("offline", command_id=self.last_command_id)
        self._publish_presence(status="offline")
        self.client.loop_stop()
        self.client.disconnect()


def main() -> None:
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
