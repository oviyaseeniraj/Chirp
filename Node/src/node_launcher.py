#!/usr/bin/env python3
"""
Chirp  –  Node pipeline launcher daemon
=======================================
Runs persistently on each radar node.  Listens for MQTT lifecycle
commands and manages the radar pipeline + FPGA.

Topics
------
Subscribed:
  chirp/v1/group/<group>/node/<node>/command
    actions: start_pipeline | stop_pipeline | start_radar | reset_radar | status

Published:
  chirp/v1/presence/<node>                      — online / offline
  chirp/v1/group/<group>/node/<node>/status     — pipeline state + uptime

Usage
-----
  sudo python3 node_launcher.py    (needs root for FPGA scripts)

Requires the same .env as main.py (MQTT_HOST, NODE_ID, GROUP_ID, etc.).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import paho.mqtt.client as mqtt

# ---- Load Node/.env so MQTT_HOST etc are picked up ---------------
_NODE_DIR = Path(os.getenv("NODE_DIR", str(Path(__file__).resolve().parents[1])))
_ENV_FILE = _NODE_DIR / ".env"
if _ENV_FILE.is_file():
    with open(_ENV_FILE) as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            k, _, v = _line.partition("=")
            k, v = k.strip(), v.split("#")[0].strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
NODE_ID = os.getenv("NODE_ID", socket.gethostname())
GROUP_ID = os.getenv("GROUP_ID", "default")
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USERNAME", NODE_ID)
MQTT_PASS = os.getenv("MQTT_PASSWORD", "")
SCHEMA_VERSION = int(os.getenv("CHIRP_SCHEMA_VERSION", "1"))
TOPIC_PREFIX = os.getenv("CHIRP_TOPIC_PREFIX", "chirp/v1")

NODE_DIR = Path(os.getenv("NODE_DIR", str(Path(__file__).resolve().parents[1])))

COMMAND_TOPIC = f"{TOPIC_PREFIX}/group/{GROUP_ID}/node/{NODE_ID}/command"
STATUS_TOPIC = f"{TOPIC_PREFIX}/group/{GROUP_ID}/node/{NODE_ID}/status"
PRESENCE_TOPIC = f"{TOPIC_PREFIX}/presence/{NODE_ID}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [LAUNCHER] %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("launcher")


def _now_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Pipeline + FPGA manager
# ---------------------------------------------------------------------------


class PipelineManager:
    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._started_ms: int = 0
        self._python = self._find_python()

    @staticmethod
    def _find_python() -> str:
        venv_py = NODE_DIR / ".venv" / "bin" / "python3"
        return str(venv_py) if venv_py.exists() else sys.executable

    # ----- Pipeline lifecycle -----------------------------------------

    def start(self) -> bool:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                log.warning("Pipeline already running (pid=%s)", self._process.pid)
                return False
            main_py = NODE_DIR / "src" / "main.py"
            if not main_py.exists():
                log.error("main.py not found at %s", main_py)
                return False
            try:
                self._process = subprocess.Popen(
                    [self._python, "-u", str(main_py)],
                    env=os.environ.copy(),
                    cwd=str(NODE_DIR),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                self._started_ms = _now_ms()
                log.info("Pipeline started  pid=%s", self._process.pid)
                return True
            except Exception as exc:
                log.exception("Failed to start pipeline: %s", exc)
                self._process = None
                return False

    def stop(self) -> bool:
        with self._lock:
            if self._process is None:
                return False
            pid = self._process.pid
            if self._process.poll() is not None:
                log.info(
                    "Pipeline already exited (pid=%s, rc=%s)",
                    pid,
                    self._process.returncode,
                )
                self._process = None
                return True
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                    self._process.wait(timeout=3)
            except ProcessLookupError:
                pass
            log.info("Pipeline stopped  pid=%s", pid)
            self._process = None
            return True

    @property
    def running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    @property
    def pid(self) -> Optional[int]:
        with self._lock:
            return self._process.pid if self._process else None

    @property
    def uptime_ms(self) -> int:
        if not self.running:
            return 0
        return _now_ms() - self._started_ms

    # ----- FPGA management (requires sudo) ----------------------------

    def _fpga_script(self, script_name: str) -> bool:
        script = NODE_DIR / "scripts" / script_name
        if not script.exists():
            log.error("Script not found: %s", script)
            return False
        try:
            result = subprocess.run(
                ["sudo", "bash", str(script)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                log.error(
                    "%s failed (rc=%s): %s",
                    script_name,
                    result.returncode,
                    result.stderr[:200],
                )
                return False
            log.info("%s completed", script_name)
            return True
        except subprocess.TimeoutExpired:
            log.error("%s timed out", script_name)
            return False
        except Exception as exc:
            log.exception("%s error: %s", script_name, exc)
            return False

    def start_radar(self) -> bool:
        return self._fpga_script("start_radar.sh")

    def reset_radar(self) -> bool:
        return self._fpga_script("reset_radar.sh")

    # ----- Status ----------------------------------------------------

    def status_payload(self) -> dict:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "nodeId": NODE_ID,
            "groupId": GROUP_ID,
            "pipelineRunning": self.running,
            "pipelinePid": self.pid,
            "uptimeMs": self.uptime_ms,
            "timestampMs": _now_ms(),
        }


# ---------------------------------------------------------------------------
# MQTT daemon
# ---------------------------------------------------------------------------


class NodeLauncher:
    def __init__(self) -> None:
        self.pipeline = PipelineManager()
        self.shutdown = threading.Event()

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"launcher-{NODE_ID}",
            clean_session=True,
        )
        if MQTT_USER:
            self.client.username_pw_set(MQTT_USER, MQTT_PASS)

        self.client.will_set(
            PRESENCE_TOPIC,
            payload=json.dumps(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "nodeId": NODE_ID,
                    "groupId": GROUP_ID,
                    "status": "offline",
                    "timestampMs": _now_ms(),
                }
            ),
            qos=1,
            retain=True,
        )

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def _publish_presence(self, status: str) -> None:
        self.client.publish(
            PRESENCE_TOPIC,
            payload=json.dumps(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "nodeId": NODE_ID,
                    "groupId": GROUP_ID,
                    "status": status,
                    "timestampMs": _now_ms(),
                }
            ),
            qos=1,
            retain=True,
        )

    def _publish_status(self) -> None:
        self.client.publish(
            STATUS_TOPIC, payload=json.dumps(self.pipeline.status_payload()), qos=1
        )

    def _on_connect(self, client, userdata, flags, rc, props):
        if rc != 0:
            log.error("MQTT connect failed  rc=%s", rc)
            return
        log.info("Connected to broker  %s:%s", MQTT_HOST, MQTT_PORT)
        client.subscribe(COMMAND_TOPIC, qos=1)
        self._publish_presence("online")
        self._publish_status()

    def _on_disconnect(self, client, userdata, flags, rc, props):
        if self.shutdown.is_set():
            log.info("Disconnected (shutdown)")
        else:
            log.warning("Unexpected disconnect  rc=%s", rc)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode()) if msg.payload else {}
        except json.JSONDecodeError:
            log.warning("Non-JSON command ignored")
            return

        action = payload.get("action", "")

        if action == "start_pipeline":
            log.info("Command: start_pipeline")
            self.pipeline.start()
            self._publish_status()
        elif action == "stop_pipeline":
            log.info("Command: stop_pipeline")
            self.pipeline.stop()
            self._publish_status()
        elif action == "start_radar":
            log.info("Command: start_radar")
            self.pipeline.start_radar()
            self._publish_status()
        elif action == "reset_radar":
            log.info("Command: reset_radar")
            self.pipeline.reset_radar()
            self._publish_status()
        elif action == "status":
            self._publish_status()
        else:
            log.warning("Unknown command action=%s", action)

    def _status_loop(self):
        while not self.shutdown.is_set():
            if self.pipeline.running:
                self._publish_status()
            time.sleep(2)

    def run(self) -> None:
        self.client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        self.client.loop_start()
        threading.Thread(target=self._status_loop, daemon=True).start()
        log.info("Node launcher running  node=%s  group=%s", NODE_ID, GROUP_ID)
        self.shutdown.wait()
        self.pipeline.stop()
        self._publish_presence("offline")
        self.client.loop_stop()
        self.client.disconnect()
        log.info("Node launcher stopped")

    def stop(self) -> None:
        self.shutdown.set()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    launcher = NodeLauncher()

    def _sig_handler(sig, frame):
        log.info("Signal %s received, shutting down", sig)
        launcher.stop()

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT, _sig_handler)
    launcher.run()


if __name__ == "__main__":
    main()
