#!/usr/bin/env python3
"""
Bird's-eye fusion dashboard — Xavier-side MQTT subscriber + web server.

Subscribes to:
  chirp/v1/group/+/frames/+              — per-node live cluster frames
  chirp/v1/group/+/calibration/result   — spatial calibration result
  chirp/v1/presence/+                   — node online/offline status

Serves a browser dashboard at http://<xavier-ip>:5002 that renders all
nodes' detections in a shared global coordinate frame (bird's-eye view).
"""

from __future__ import annotations

import asyncio
import cmath
import json
import logging
import math
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import paho.mqtt.client as mqtt
import socketio
from aiohttp import web
from jinja2 import Environment, FileSystemLoader

# ---------------------------------------------------------------------------
# Config (env vars)
# ---------------------------------------------------------------------------
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USERNAME", os.getenv("MQTT_SERVER_USER", "server-xavier"))
MQTT_PASS = os.getenv("MQTT_PASSWORD", os.getenv("MQTT_SERVER_PASS", ""))
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "5002"))
TOPIC_PREFIX = "chirp/v1"

# How long (ms) before a node's last-seen frame is considered stale
NODE_STALE_MS = int(os.getenv("NODE_STALE_MS", "3000"))

# ---------------------------------------------------------------------------
# Node colour palette (consistent per index)
# ---------------------------------------------------------------------------
NODE_COLORS = ["#00d4ff", "#ff6b35", "#7fff00", "#ff00ff", "#ffd700", "#ff4444"]


def _node_color(node_id: str, node_ids: List[str]) -> str:
    try:
        return NODE_COLORS[node_ids.index(node_id) % len(NODE_COLORS)]
    except ValueError:
        return "#ffffff"


# ---------------------------------------------------------------------------
# Coordinate transform
# ---------------------------------------------------------------------------

def _polar_to_local_xy(range_m: float, angle_rad: float) -> Tuple[float, float]:
    """Radar polar (range, azimuth) → local Cartesian (x=left/right, y=depth)."""
    return range_m * math.sin(angle_rad), range_m * math.cos(angle_rad)


def _apply_calibration(
    range_m: float,
    angle_rad: float,
    node_idx: int,
    calib: Optional[Dict],
) -> Tuple[float, float]:
    """
    Transform a detection from node node_idx's local frame into the global
    (reference node 0) coordinate frame using the closed-form calibration result.

    Returns (x_global, y_global) in metres.
    """
    x_local, y_local = _polar_to_local_xy(range_m, angle_rad)

    if calib is None or node_idx == 0:
        return x_local, y_local

    try:
        theta_deg = calib["theta_opt"][0][node_idx]
        P_cell = calib["P_opt"][0][node_idx]        # [real, imag]
        theta_rad = math.radians(theta_deg)
        z_local = complex(x_local, y_local)
        z_global = cmath.exp(1j * theta_rad) * z_local + complex(P_cell[0], P_cell[1])
        return z_global.real, z_global.imag
    except (IndexError, TypeError, KeyError):
        return x_local, y_local


# ---------------------------------------------------------------------------
# Shared state (written by MQTT thread, read by async handlers)
# ---------------------------------------------------------------------------

class DashboardState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # node_id -> {clusters, timestampMs, color}
        self.node_frames: Dict[str, Dict] = {}
        # calibration result payload (None until first result arrives)
        self.calibration: Optional[Dict] = None
        # node_id -> {status, timestampMs}
        self.presence: Dict[str, Dict] = {}

    def update_frame(self, node_id: str, payload: Dict) -> None:
        with self._lock:
            self.node_frames[node_id] = {
                "clusters": payload.get("clusters", []),
                "timestampMs": payload.get("timestampMs", 0),
                "groupId": payload.get("groupId", ""),
            }

    def update_calibration(self, payload: Dict) -> None:
        with self._lock:
            if payload.get("ok", False):
                self.calibration = payload
                logging.info(
                    "[DASHBOARD] Calibration loaded commandId=%s nodes=%s",
                    payload.get("commandId"),
                    payload.get("nodeIds"),
                )

    def update_presence(self, node_id: str, payload: Dict) -> None:
        with self._lock:
            self.presence[node_id] = {
                "status": payload.get("status", "unknown"),
                "timestampMs": payload.get("timestampMs", 0),
            }

    def build_fused_snapshot(self) -> Dict:
        """Return a snapshot ready to emit to the browser."""
        with self._lock:
            calib = self.calibration
            node_ids = calib["nodeIds"] if calib else sorted(self.node_frames.keys())
            now_ms = int(time.time() * 1000)

            points: List[Dict] = []
            node_status: List[Dict] = []

            for node_id, frame in self.node_frames.items():
                try:
                    node_idx = node_ids.index(node_id)
                except ValueError:
                    node_idx = 0

                color = NODE_COLORS[node_idx % len(NODE_COLORS)]
                age_ms = now_ms - frame["timestampMs"]
                stale = age_ms > NODE_STALE_MS

                for c in frame["clusters"]:
                    x, y = _apply_calibration(
                        c.get("range_m", 0.0),
                        c.get("angle_rad", 0.0),
                        node_idx,
                        calib,
                    )
                    points.append({
                        "x": round(x, 3),
                        "y": round(y, 3),
                        "doppler_mps": round(c.get("doppler_mps", 0.0), 3),
                        "mass": c.get("mass", 1),
                        "node_id": node_id,
                        "color": color,
                        "stale": stale,
                    })

                node_status.append({
                    "node_id": node_id,
                    "color": color,
                    "cluster_count": len(frame["clusters"]),
                    "age_ms": age_ms,
                    "stale": stale,
                })

            # Node positions in global frame (P_opt column 0 of each node = offset from ref)
            node_positions: List[Dict] = []
            if calib:
                for ki, nid in enumerate(calib.get("nodeIds", [])):
                    color = NODE_COLORS[ki % len(NODE_COLORS)]
                    if ki == 0:
                        node_positions.append({"node_id": nid, "x": 0.0, "y": 0.0, "color": color})
                    else:
                        try:
                            P = calib["P_opt"][0][ki]
                            node_positions.append({
                                "node_id": nid,
                                "x": round(float(P[0]), 3),
                                "y": round(float(P[1]), 3),
                                "color": color,
                            })
                        except (IndexError, TypeError):
                            pass

            presence_list = [
                {
                    "node_id": nid,
                    "status": info["status"],
                    "color": NODE_COLORS[
                        (node_ids.index(nid) if nid in node_ids else 0) % len(NODE_COLORS)
                    ],
                }
                for nid, info in self.presence.items()
            ]

            return {
                "timestampMs": now_ms,
                "calibrated": calib is not None,
                "calibration_command_id": calib.get("commandId") if calib else None,
                "node_ids": node_ids,
                "points": points,
                "node_status": node_status,
                "node_positions": node_positions,
                "presence": presence_list,
            }


STATE = DashboardState()


# ---------------------------------------------------------------------------
# MQTT subscriber
# ---------------------------------------------------------------------------

def _build_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="dashboard-xavier",
        clean_session=True,
    )
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    def on_connect(c, userdata, flags, reason_code, properties):
        if reason_code != 0:
            logging.error("[DASHBOARD] MQTT connect failed reason_code=%s", reason_code)
            return
        logging.info("[DASHBOARD] MQTT connected to %s:%d", MQTT_HOST, MQTT_PORT)
        c.subscribe(f"{TOPIC_PREFIX}/group/+/frames/+", qos=0)
        c.subscribe(f"{TOPIC_PREFIX}/group/+/calibration/result", qos=1)
        c.subscribe(f"{TOPIC_PREFIX}/presence/+", qos=1)

    def on_message(c, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode()) if msg.payload else {}
        except json.JSONDecodeError:
            return

        topic = msg.topic
        parts = topic.split("/")

        if "/frames/" in topic:
            node_id = parts[-1]
            STATE.update_frame(node_id, payload)

        elif "/calibration/result" in topic:
            STATE.update_calibration(payload)

        elif topic.startswith(f"{TOPIC_PREFIX}/presence/"):
            node_id = parts[-1]
            STATE.update_presence(node_id, payload)

    client.on_connect = on_connect
    client.on_message = on_message
    return client


# ---------------------------------------------------------------------------
# Web / Socket.IO server
# ---------------------------------------------------------------------------

sio = socketio.AsyncServer(async_mode="aiohttp", cors_allowed_origins="*")
app = web.Application()
sio.attach(app)

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))


@sio.event
async def connect(sid, environ):
    logging.info("[DASHBOARD] Browser client connected sid=%s", sid)


@sio.event
async def disconnect(sid):
    logging.info("[DASHBOARD] Browser client disconnected sid=%s", sid)


async def index_handler(request):
    template = jinja_env.get_template("dashboard.html")
    return web.Response(text=template.render(), content_type="text/html")


async def status_handler(request):
    return web.Response(text="Dashboard UP", content_type="text/plain")


app.router.add_get("/", index_handler)
app.router.add_get("/status", status_handler)


# ---------------------------------------------------------------------------
# Background task: push fused snapshot to all connected browsers at ~10 Hz
# ---------------------------------------------------------------------------

async def _broadcast_loop():
    while True:
        try:
            snapshot = STATE.build_fused_snapshot()
            await sio.emit("fused_frame", snapshot)
        except Exception as exc:
            logging.warning("[DASHBOARD] Broadcast error: %s", exc)
        await asyncio.sleep(0.1)


async def _start_background_tasks(app_: web.Application):
    app_["broadcast_task"] = asyncio.create_task(_broadcast_loop())


async def _cleanup_background_tasks(app_: web.Application):
    app_["broadcast_task"].cancel()
    try:
        await app_["broadcast_task"]
    except asyncio.CancelledError:
        pass


app.on_startup.append(_start_background_tasks)
app.on_cleanup.append(_cleanup_background_tasks)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if not MQTT_PASS:
        logging.warning(
            "[DASHBOARD] MQTT_PASSWORD / MQTT_SERVER_PASS not set — broker auth will fail"
        )

    mqtt_client = _build_mqtt_client()
    try:
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    except Exception as exc:
        logging.error("[DASHBOARD] Cannot connect to MQTT broker: %s", exc)
    mqtt_client.loop_start()

    logging.info(
        "[DASHBOARD] Starting bird's-eye dashboard on http://0.0.0.0:%d", DASHBOARD_PORT
    )
    web.run_app(app, host="0.0.0.0", port=DASHBOARD_PORT, access_log=None)

    mqtt_client.loop_stop()
    mqtt_client.disconnect()


if __name__ == "__main__":
    main()
