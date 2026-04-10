#!/usr/bin/env python3
"""Laptop CLI for Chirp MQTT start requests (implementation step 4)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
import uuid
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt

SCHEMA_VERSION = 1
TOPIC_PREFIX = "chirp/v1"
START_REQUEST_TOPIC = f"{TOPIC_PREFIX}/server/start/request" # published topic
START_RESULT_TOPIC = f"{TOPIC_PREFIX}/server/start/result"   # subscribed topic


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


def _parse_capture_config(args: argparse.Namespace) -> Dict[str, Any]:
    if args.capture_config_json and args.capture_config_file:
        raise ValueError("Use only one of --capture-config-json or --capture-config-file.")

    if args.capture_config_json:
        parsed = json.loads(args.capture_config_json)
    elif args.capture_config_file:
        with open(args.capture_config_file, "r", encoding="utf-8") as f:
            parsed = json.load(f)
    else:
        parsed = {}

    if not isinstance(parsed, dict):
        raise ValueError("captureConfig must be a JSON object.")
    return parsed


class LaptopTriggerClient:
    def __init__(
        self,
        *,
        mqtt_host: str,
        mqtt_port: int,
        mqtt_user: str,
        mqtt_pass: str,
        client_id: str,
        group_id: str,
        capture_config: Dict[str, Any],
        requested_delay_ms: Optional[int],
        timeout_ms: int,
        print_json: bool,
    ) -> None:
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.mqtt_user = mqtt_user  # laptop username
        self.mqtt_pass = mqtt_pass  # laptop password
        self.client_id = client_id
        self.group_id = group_id
        self.capture_config = capture_config
        self.requested_delay_ms = requested_delay_ms
        self.timeout_ms = timeout_ms
        self.print_json = print_json

        self.request_id = f"req-{uuid.uuid4().hex[:12]}"
        self.result_event = threading.Event()
        self.result_payload: Optional[Dict[str, Any]] = None
        self.connect_failed_reason: Optional[str] = None
        self.stop_event = threading.Event()

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            clean_session=False,
        )
        
        if self.mqtt_user:
            self.client.username_pw_set(self.mqtt_user, self.mqtt_pass)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _request_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "timestampMs": _now_ms(),
            "requestId": self.request_id,
            "groupId": self.group_id,
            "captureConfig": self.capture_config,
        }
        if self.requested_delay_ms is not None:
            payload["requestedDelayMs"] = self.requested_delay_ms
        return payload

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        if reason_code != 0:
            self.connect_failed_reason = str(reason_code)
            self.result_event.set()
            return

        logging.info("Connected to broker at %s:%d", self.mqtt_host, self.mqtt_port)
        client.subscribe(START_RESULT_TOPIC, qos=1)
        request_payload = self._request_payload()
        client.publish(START_REQUEST_TOPIC, payload=json.dumps(request_payload), qos=1, retain=False)
        logging.info(
            "Published start request requestId=%s groupId=%s topic=%s",
            self.request_id,
            self.group_id,
            START_REQUEST_TOPIC,
        )

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        if self.stop_event.is_set():
            return
        logging.warning("MQTT disconnected unexpectedly reason_code=%s", reason_code)

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        if msg.topic != START_RESULT_TOPIC:
            return
        try:
            payload = json.loads(msg.payload.decode("utf-8")) if msg.payload else {}
        except json.JSONDecodeError:
            logging.warning("Skipping non-JSON payload on topic=%s", msg.topic)
            return

        request_id = payload.get("requestId")
        if request_id != self.request_id:
            return

        self.result_payload = payload
        self.result_event.set()

    def run(self) -> int:
        self.client.connect(self.mqtt_host, self.mqtt_port, keepalive=30)
        self.client.loop_start()

        completed = self.result_event.wait(timeout=self.timeout_ms / 1000.0)
        self.stop_event.set()
        self.client.loop_stop()
        self.client.disconnect()

        if self.connect_failed_reason is not None:
            print(
                f"ERROR: Failed to connect/authenticate to MQTT broker "
                f"{self.mqtt_host}:{self.mqtt_port} (reason={self.connect_failed_reason})."
            )
            return 2

        if not completed or self.result_payload is None:
            print(
                f"ERROR: Timed out waiting for start result on {START_RESULT_TOPIC} "
                f"for requestId={self.request_id}."
            )
            return 3

        if self.print_json:
            print(json.dumps(self.result_payload, indent=2, sort_keys=True))
        else:
            self._print_summary(self.result_payload)

        return 0 if bool(self.result_payload.get("ok", False)) else 4

    def _print_summary(self, payload: Dict[str, Any]) -> None:
        ok = bool(payload.get("ok", False))
        reason = payload.get("reason", "unknown")
        command_id = payload.get("commandId", "-")
        start_epoch_ms = payload.get("startEpochMs", "-")
        summary = payload.get("summary", {}) or {}
        target_nodes = payload.get("targetNodeIds", []) or []
        acked_nodes = payload.get("ackedNodeIds", []) or []
        missing_nodes = payload.get("missingNodeIds", []) or []
        not_ready_nodes = payload.get("notReadyNodeIds", []) or []

        print("")
        print("=== Chirp Start Result ===")
        print(f"requestId       : {self.request_id}")
        print(f"ok              : {ok}")
        print(f"reason          : {reason}")
        print(f"groupId         : {self.group_id}")
        print(f"commandId       : {command_id}")
        print(f"startEpochMs    : {start_epoch_ms}")
        print(f"expectedNodeCnt : {summary.get('expectedNodeCount', 0)}")
        print(f"ackCount        : {summary.get('ackCount', 0)}")
        print(f"readyCount      : {summary.get('readyCount', 0)}")
        print(f"missingCount    : {summary.get('missingCount', 0)}")
        print(f"targetNodeIds   : {target_nodes}")
        print(f"ackedNodeIds    : {acked_nodes}")
        if missing_nodes:
            print(f"missingNodeIds  : {missing_nodes}")
        if not_ready_nodes:
            print(f"notReadyNodeIds : {not_ready_nodes}")
        print("==========================")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish Chirp start request from laptop and wait for result.",
    )
    parser.add_argument("--group-id", required=True, help="Target radar groupId.")
    parser.add_argument(
        "--requested-delay-ms",
        type=int,
        default=None,
        help="Optional requested start delay in ms (server clamps by policy).",
    )
    parser.add_argument(
        "--capture-config-json",
        default=None,
        help="Inline JSON object for captureConfig.",
    )
    parser.add_argument(
        "--capture-config-file",
        default=None,
        help="Path to JSON file containing captureConfig object.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=_env_int("LAPTOP_TRIGGER_TIMEOUT_MS", 12000),
        help="Max time to wait for server/start/result.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print full result payload JSON instead of summary lines.",
    )
    return parser


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        capture_config = _parse_capture_config(args)
    except Exception as exc:
        print(f"ERROR: Invalid capture config: {exc}")
        return 2

    mqtt_host = os.getenv("MQTT_HOST", "127.0.0.1")
    mqtt_port = _env_int("MQTT_PORT", 1883)
    mqtt_user = os.getenv("MQTT_LAPTOP_USER", "laptop-control")
    mqtt_pass = os.getenv("MQTT_LAPTOP_PASS", "")
    client_id = mqtt_user

    if not mqtt_pass:
        print("ERROR: Missing MQTT password. Set MQTT_LAPTOP_PASS.")
        return 2

    client = LaptopTriggerClient(
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        mqtt_user=mqtt_user,
        mqtt_pass=mqtt_pass,
        client_id=client_id,
        group_id=args.group_id,
        capture_config=capture_config,
        requested_delay_ms=args.requested_delay_ms,
        timeout_ms=max(1000, args.timeout_ms),
        print_json=args.print_json,
    )

    def _signal_handler(sig: int, frame: Any) -> None:
        del frame
        print(f"\nSignal {sig} received. Exiting.")
        client.stop_event.set()
        client.result_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    return client.run()


if __name__ == "__main__":
    sys.exit(main())
