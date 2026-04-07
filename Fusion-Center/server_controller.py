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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import paho.mqtt.client as mqtt


SCHEMA_VERSION = 1
TOPIC_PREFIX = "chirp/v1"
START_REQUEST_TOPIC = f"{TOPIC_PREFIX}/server/start/request"    # subscribed topic
START_RESULT_TOPIC = f"{TOPIC_PREFIX}/server/start/result"      # published topic
SERVER_STATUS_TOPIC = f"{TOPIC_PREFIX}/server/status"           # published topic
PRESENCE_TOPIC_FILTER = f"{TOPIC_PREFIX}/presence/+"
STATE_TOPIC_FILTER = f"{TOPIC_PREFIX}/group/+/capture/state/+"
ACK_TOPIC_FILTER = f"{TOPIC_PREFIX}/group/+/capture/ack/+"

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

        self.lead_time_ms = _env_int("CHIRP_LEAD_TIME_MS", 3000)
        self.min_start_delay_ms = _env_int("CHIRP_MIN_START_DELAY_MS", 1000)
        self.max_start_delay_ms = _env_int("CHIRP_MAX_START_DELAY_MS", 10000)
        self.ack_timeout_ms = _env_int("CHIRP_ACK_TIMEOUT_MS", 5000)
        self.presence_stale_ms = _env_int("CHIRP_PRESENCE_STALE_MS", 6000)
        self.state_stale_ms = _env_int("CHIRP_STATE_STALE_MS", 10000)

        self.shutdown_event = threading.Event()
        self.presence_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.command_lock = threading.Lock()

        self.presence: Dict[str, Dict[str, Any]] = {} # what nodes are alive?
        self.state: Dict[Tuple[str, str], Dict[str, Any]] = {} # what state are the nodes in? the tuple is (group_id, node_id)
        self.active_commands: Dict[str, ActiveCommand] = {} 

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
        client.subscribe(START_REQUEST_TOPIC, qos=1) # request from laptop to server 
        client.subscribe(PRESENCE_TOPIC_FILTER, qos=1) # each radar node sends its status + group membership to server
        client.subscribe(STATE_TOPIC_FILTER, qos=1) # each radar node sends its current state (error, offline, etc.) to server 
        client.subscribe(ACK_TOPIC_FILTER, qos=1) # each radar node sends an ACK to the server

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
