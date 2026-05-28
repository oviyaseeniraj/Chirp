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

# MQTT / pipeline env vars — logged immediately after .env load + config init
_PIPELINE_ENV_KEYS = [
    "MQTT_HOST",
    "MQTT_PORT",
    "MQTT_USERNAME",
    "MQTT_PASSWORD",
    "NODE_ID",
    "GROUP_ID",
    "SERVER_URL",
    "CHIRP_TRIGGER_MODE",
    "CHIRP_SCHEMA_VERSION",
    "CHIRP_TOPIC_PREFIX",
]


def _log_pipeline_env() -> None:
    """Log key env vars the pipeline subprocess will inherit (redact password)."""
    for k in _PIPELINE_ENV_KEYS:
        v = os.getenv(k, "<unset>")
        if k.endswith("PASSWORD") and v != "<unset>":
            v = "***"
        log.info("env: %s=%s", k, v)


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

# ---- Back-propagate resolved defaults into os.environ so the pipeline
#     subprocess (full_integration_test.py) inherits every value it needs.
os.environ.setdefault("NODE_ID", NODE_ID)
os.environ.setdefault("GROUP_ID", GROUP_ID)
os.environ.setdefault("MQTT_HOST", MQTT_HOST)
os.environ.setdefault("MQTT_PORT", str(MQTT_PORT))
os.environ.setdefault("MQTT_USERNAME", MQTT_USER)
os.environ.setdefault("MQTT_PASSWORD", MQTT_PASS)
os.environ.setdefault("SERVER_URL", "http://127.0.0.1:5001")

# Trigger (clock source) selection — matches run_tests.sh modes
TRIGGER_MODE = os.getenv("CHIRP_TRIGGER_MODE", "none").lower()
os.environ.setdefault("CHIRP_TRIGGER_MODE", TRIGGER_MODE)
_TRIGGER_PATHS: dict[str, list[str]] = {
    "local": [str(NODE_DIR / "src" / "hardware_trigger" / "local_trigger")],
    "networked": [str(NODE_DIR / "src" / "hardware_trigger" / "networked_trigger")],
    "mqtt": [
        str(NODE_DIR / ".venv" / "bin" / "python3"),
        str(NODE_DIR / "src" / "hardware_trigger_mqtt" / "mqtt_trigger_client.py"),
    ],
}

COMMAND_TOPIC = f"{TOPIC_PREFIX}/group/{GROUP_ID}/node/{NODE_ID}/command"
STATUS_TOPIC = f"{TOPIC_PREFIX}/group/{GROUP_ID}/node/{NODE_ID}/status"
PRESENCE_TOPIC = f"{TOPIC_PREFIX}/presence/{NODE_ID}"

_VERBOSITY = int(os.getenv("LAUNCHER_LOG_LEVEL", "0"))
_PY_LOG_LEVEL = {0: logging.INFO, 1: logging.DEBUG, 2: logging.DEBUG}.get(
    _VERBOSITY, logging.INFO
)

logging.basicConfig(
    level=_PY_LOG_LEVEL,
    format="%(asctime)s [LAUNCHER] %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("launcher")
log.debug("Verbosity=%s  py_level=%s", _VERBOSITY, logging.getLevelName(_PY_LOG_LEVEL))
log.debug(
    "Config: NODE_ID=%s  GROUP_ID=%s  MQTT_HOST=%s:%s  TOPIC_PREFIX=%s",
    NODE_ID,
    GROUP_ID,
    MQTT_HOST,
    MQTT_PORT,
    TOPIC_PREFIX,
)
log.debug(
    "Topics: cmd=%s  status=%s  presence=%s",
    COMMAND_TOPIC,
    STATUS_TOPIC,
    PRESENCE_TOPIC,
)
log.debug(
    "NODE_DIR=%s  MQTT_USER=%s  TRIGGER_MODE=%s", NODE_DIR, MQTT_USER, TRIGGER_MODE
)
_log_pipeline_env()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _dump_script_output(script_name: str, stdout: str, stderr: str) -> None:
    """Log full script stdout and stderr at verbosity level 2."""
    if _VERBOSITY < 2:
        return
    for stream_name, text in (("stdout", stdout), ("stderr", stderr)):
        if text.strip():
            log.info("--- %s %s ---\n%s", script_name, stream_name, text.strip())


# ---------------------------------------------------------------------------
# Pipeline + FPGA manager
# ---------------------------------------------------------------------------


class PipelineManager:
    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None
        self._trigger: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._started_ms: int = 0
        self._trigger_started_ms: int = 0
        self._python = self._find_python()

    @staticmethod
    def _find_python() -> str:
        venv_py = NODE_DIR / ".venv" / "bin" / "python3"
        if venv_py.exists():
            log.debug("Using venv python: %s", venv_py)
            return str(venv_py)
        log.debug("Using system python: %s", sys.executable)
        return sys.executable

    # ----- Trigger / clock source ------------------------------------

    def _start_trigger(self) -> bool:
        """Launch the hardware trigger binary or MQTT trigger client."""
        if TRIGGER_MODE == "none":
            log.info(
                "Trigger mode=none — skipping clock source (pipeline must provide its own timing)"
            )
            return True
        if TRIGGER_MODE not in _TRIGGER_PATHS:
            log.error(
                "Unknown trigger mode: %s (valid: %s)",
                TRIGGER_MODE,
                list(_TRIGGER_PATHS),
            )
            return False

        cmd = _TRIGGER_PATHS[TRIGGER_MODE]
        exe = Path(cmd[0])
        if not exe.exists():
            log.error("Trigger binary not found: %s", exe)
            return False

        try:
            log.info("Starting trigger (mode=%s): %s", TRIGGER_MODE, " ".join(cmd))
            self._trigger = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._trigger_started_ms = _now_ms()
            log.info("Trigger started  pid=%s", self._trigger.pid)
            return True
        except Exception as exc:
            log.exception("Failed to start trigger: %s", exc)
            self._trigger = None
            return False

    def _stop_trigger(self) -> None:
        if self._trigger is None:
            return
        pid = self._trigger.pid
        if self._trigger.poll() is not None:
            log.debug(
                "Trigger already exited (pid=%s, rc=%s)", pid, self._trigger.returncode
            )
            self._trigger = None
            return
        try:
            pgid = os.getpgid(pid)
            log.debug("Stopping trigger pgid=%s (pid=%s)", pgid, pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                self._trigger.wait(timeout=3)
            except subprocess.TimeoutExpired:
                log.warning(
                    "Trigger did not exit on SIGTERM, sending SIGKILL  pid=%s", pid
                )
                os.killpg(pgid, signal.SIGKILL)
                self._trigger.wait(timeout=2)
        except ProcessLookupError:
            log.debug("Trigger process already gone  pid=%s", pid)
        log.info("Trigger stopped  pid=%s", pid)
        self._trigger = None

    @property
    def trigger_running(self) -> bool:
        with self._lock:
            return self._trigger is not None and self._trigger.poll() is None

    @property
    def trigger_pid(self) -> Optional[int]:
        with self._lock:
            return self._trigger.pid if self._trigger else None

    # ----- Pipeline lifecycle -----------------------------------------

    def start(self) -> bool:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                log.warning("Pipeline already running (pid=%s)", self._process.pid)
                return False

            # Start clock source first
            if not self._start_trigger():
                return False

            main_py = NODE_DIR / "src" / "main.py"
            if not main_py.exists():
                log.error("main.py not found at %s", main_py)
                self._stop_trigger()
                return False
            try:
                log.debug(
                    "Launching pipeline: %s -u %s  cwd=%s",
                    self._python,
                    main_py,
                    NODE_DIR,
                )
                _log_pipeline_env()
                child_env = os.environ.copy()
                self._process = subprocess.Popen(
                    [self._python, "-u", str(main_py)],
                    env=child_env,
                    cwd=str(NODE_DIR),
                    start_new_session=True,
                    close_fds=True,
                )
                self._started_ms = _now_ms()
                log.info("Pipeline started  pid=%s", self._process.pid)
                return True
            except Exception as exc:
                log.exception("Failed to start pipeline: %s", exc)
                self._process = None
                self._stop_trigger()
                return False

    def stop(self) -> bool:
        with self._lock:
            # Stop pipeline first, then trigger
            pipeline_stopped = False
            if self._process is not None:
                pid = self._process.pid
                if self._process.poll() is not None:
                    log.info(
                        "Pipeline already exited (pid=%s, rc=%s)",
                        pid,
                        self._process.returncode,
                    )
                    self._process = None
                    pipeline_stopped = True
                else:
                    try:
                        pgid = os.getpgid(pid)
                        log.debug("Sending SIGTERM to pgid=%s (pid=%s)", pgid, pid)
                        os.killpg(pgid, signal.SIGTERM)
                        try:
                            self._process.wait(timeout=5)
                            log.debug("Pipeline exited gracefully  pid=%s", pid)
                        except subprocess.TimeoutExpired:
                            log.warning(
                                "Pipeline did not exit on SIGTERM, sending SIGKILL  pid=%s",
                                pid,
                            )
                            os.killpg(pgid, signal.SIGKILL)
                            self._process.wait(timeout=3)
                            log.debug("Pipeline killed  pid=%s", pid)
                    except ProcessLookupError:
                        log.debug("Process already gone  pid=%s", pid)
                    log.info("Pipeline stopped  pid=%s", pid)
                    self._process = None
                    pipeline_stopped = True

            # Always try to stop the trigger
            self._stop_trigger()
            return pipeline_stopped

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
        log.debug("Executing FPGA script: %s", script)
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
                _dump_script_output(script_name, result.stdout, result.stderr)
                return False
            log.info("%s completed", script_name)
            _dump_script_output(script_name, result.stdout, result.stderr)
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
            "triggerMode": TRIGGER_MODE,
            "triggerRunning": self.trigger_running,
            "triggerPid": self.trigger_pid,
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
        log.debug("Publishing presence: %s -> %s", status, PRESENCE_TOPIC)
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
        payload = self.pipeline.status_payload()
        log.debug("Publishing status: %s", payload)
        self.client.publish(STATUS_TOPIC, payload=json.dumps(payload), qos=1)

    def _on_connect(self, client, userdata, flags, rc, props):
        if rc != 0:
            log.error("MQTT connect failed  rc=%s", rc)
            return
        log.info("Connected to broker  %s:%s", MQTT_HOST, MQTT_PORT)
        log.debug("Subscribing to: %s", COMMAND_TOPIC)
        result = client.subscribe(COMMAND_TOPIC, qos=1)
        log.debug("Subscribe result: %s", result)
        self._publish_presence("online")
        self._publish_status()

    def _on_disconnect(self, client, userdata, flags, rc, props):
        if self.shutdown.is_set():
            log.info("Disconnected (shutdown)")
        else:
            log.warning("Unexpected disconnect  rc=%s  flags=%s", rc, flags)

    def _on_message(self, client, userdata, msg):
        log.debug("MQTT message received on %s: %s", msg.topic, msg.payload[:200])
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
            log.warning("Unknown command action=%s  full_payload=%s", action, payload)

    def _status_loop(self):
        log.debug("Status loop started")
        while not self.shutdown.is_set():
            self._publish_status()
            time.sleep(1)
        log.debug("Status loop stopped")

    def run(self) -> None:
        log.debug(
            "Connecting to broker  host=%s:%s  keepalive=30", MQTT_HOST, MQTT_PORT
        )
        self.client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        self.client.loop_start()
        threading.Thread(target=self._status_loop, daemon=True).start()
        log.info("Node launcher running  node=%s  group=%s", NODE_ID, GROUP_ID)
        self.shutdown.wait()
        log.debug("Shutdown signal received, stopping pipeline")
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
