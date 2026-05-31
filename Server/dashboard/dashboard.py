#!/usr/bin/env python3
"""
Chirp  –  Multi‑node debug dashboard
=====================================
MQTT subscriber + aiohttp web server with Socket.IO real‑time push.

Subscribes to:
  chirp/v1/group/+/frames/+              — per-node live clusters + tracks
  chirp/v1/group/+/calibration/result    — calibration transform
  chirp/v1/presence/+                    — node online/offline

Serves a debug page at http://<host>:5002 with a single x‑y plot
showing every node's detections and confirmed tracks in one canvas,
transformed into a global coordinate frame via calibration.

Includes a calibration trigger button that publishes to
  chirp/v1/server/start/request
"""

from __future__ import annotations

import asyncio
import cmath
import json
import logging
import math
import os
import threading
import time
import uuid
import psycopg2
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import paho.mqtt.client as mqtt
import socketio
from aiohttp import web
from jinja2 import Environment, FileSystemLoader

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MQTT_HOST = os.getenv("MQTT_HOST", "nanomq")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER") or os.getenv("MQTT_SERVER_USER") or "chirp"
MQTT_PASS = os.getenv("MQTT_PASS") or os.getenv("MQTT_SERVER_PASS") or "chirp"
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "5002"))
TOPIC_PREFIX = "chirp/v1"
NODE_STALE_MS = int(os.getenv("NODE_STALE_MS", "3000"))

# Database configuration
DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "chirp")
DB_USER = os.getenv("DB_USER", "chirp")
DB_PASS = os.getenv("DB_PASS", "chirp")

NODE_COLORS = [
    "#00d4ff",
    "#ff6b35",
    "#7fff00",
    "#ff00ff",
    "#ffd700",
    "#ff4444",
    "#44ffaa",
    "#aa44ff",
]

log = logging.getLogger("dashboard")


def _node_color(node_id: str, node_ids: List[str]) -> str:
    try:
        return NODE_COLORS[node_ids.index(node_id) % len(NODE_COLORS)]
    except ValueError:
        return "#ffffff"

# new helper to prefer DNS hostnames (nodeX) over raw IPs
def _choose_hostname(node_id: str, ip_addr: Optional[str]) -> str:
    candidates = []
    if node_id:
        candidates.append(node_id)
    # if node_id looks numeric or doesn't start with "node", try "node{node_id}"
    if node_id and not node_id.lower().startswith("node"):
        candidates.append(f"node{node_id}")
    if ip_addr:
        candidates.append(ip_addr)
    for c in candidates:
        try:
            # rely on DNS resolution: if it resolves, use it
            socket.gethostbyname(c)
            return c
        except Exception:
            continue
    # fallback: prefer nodeX if possible, else ip, else node_id, else "Unknown"
    if node_id:
        return f"node{node_id}" if not node_id.lower().startswith("node") else node_id
    if ip_addr:
        return ip_addr
    return "Unknown"


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------


def _polar_to_xy(range_m: float, angle_rad: float) -> Tuple[float, float]:
    return range_m * math.sin(angle_rad), range_m * math.cos(angle_rad)


def _apply_calib(
    range_m: float,
    angle_rad: float,
    node_idx: int,
    calib: Optional[Dict],
) -> Tuple[float, float]:
    x_local, y_local = _polar_to_xy(range_m, angle_rad)
    if calib is None or node_idx == 0:
        return x_local, y_local
    try:
        theta_deg = calib["theta_opt"][0][node_idx]
        P = calib["P_opt"][0][node_idx]
        theta_rad = math.radians(theta_deg)
        z = cmath.exp(1j * theta_rad) * complex(x_local, y_local) + complex(P[0], P[1])
        return z.real, z.imag
    except (IndexError, TypeError, KeyError):
        return x_local, y_local


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------


class State:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.frames: Dict[str, Dict] = {}
        self.calibration: Optional[Dict] = None
        self.presence: Dict[str, Dict] = {}
        self.node_status: Dict[str, dict] = {}  # node_id -> pipeline status
        self.node_ips: Dict[str, str] = {}      # node_id -> ip_address

    def update_frame(self, node_id: str, payload: Dict) -> None:
        with self._lock:
            self.frames[node_id] = {
                "clusters": payload.get("clusters", []),
                "tracks": payload.get("tracks", []),
                "timestampMs": payload.get("timestampMs", 0),
            }

    def update_calibration(self, payload: Dict) -> None:
        with self._lock:
            if payload.get("ok"):
                self.calibration = payload
                log.info("Calibration loaded  commandId=%s", payload.get("commandId"))
            else:
                self.calibration = None
                log.info("Calibration cleared  reason=%s", payload.get("reason"))

    def update_presence(self, node_id: str, payload: Dict) -> None:
        with self._lock:
            self.presence[node_id] = {
                "status": payload.get("status", "unknown"),
                "timestampMs": payload.get("timestampMs", 0),
            }

    def update_node_status(self, node_id: str, payload: Dict) -> None:
        with self._lock:
            self.node_status[node_id] = {
                "pipelineRunning": payload.get("pipelineRunning", False),
                "triggerRunning": payload.get("triggerRunning", False),
                "triggerMode": payload.get("triggerMode", ""),
                "uptimeMs": payload.get("uptimeMs", 0),
                "pipelinePid": payload.get("pipelinePid"),
                "timestampMs": payload.get("timestampMs", 0),
            }

    def snapshot(self) -> Dict:
        with self._lock:
            calib = self.calibration
            node_ids = (
                calib.get("nodeIds")
                or calib.get("node_ids")
                or sorted(self.frames.keys())
            ) if calib else sorted(self.frames.keys())
            now_ms = int(time.time() * 1000)
            points, tracks_list, nodes_detail = [], [], []

            for node_id, frame in self.frames.items():
                try:
                    nidx = node_ids.index(node_id)
                except ValueError:
                    nidx = 0
                color = NODE_COLORS[nidx % len(NODE_COLORS)]
                age = now_ms - frame["timestampMs"]
                stale = age > NODE_STALE_MS

                for c in frame["clusters"]:
                    x, y = _apply_calib(
                        c.get("range_m", 0), c.get("angle_rad", 0), nidx, calib
                    )
                    points.append(
                        {
                            "x": round(x, 3),
                            "y": round(y, 3),
                            "doppler": round(c.get("doppler_mps", 0), 3),
                            "mass": c.get("mass", 1),
                            "node_id": node_id,
                            "color": color,
                            "stale": stale,
                        }
                    )

                for t in frame["tracks"]:
                    x, y = float(t.get("x", 0)), float(t.get("y", 0))
                    if calib and nidx > 0:
                        try:
                            td = calib["theta_opt"][0][nidx]
                            P = calib["P_opt"][0][nidx]
                            z = cmath.exp(1j * math.radians(td)) * complex(
                                x, y
                            ) + complex(P[0], P[1])
                            x, y = z.real, z.imag
                        except Exception:
                            pass
                    tracks_list.append(
                        {
                            "track_id": int(t.get("track_id", 0)),
                            "x": round(x, 3),
                            "y": round(y, 3),
                            "vx": round(float(t.get("vx", 0)), 3),
                            "vy": round(float(t.get("vy", 0)), 3),
                            "node_id": node_id,
                            "color": color,
                        }
                    )

                nodes_detail.append(
                    {
                        "node_id": node_id,
                        "color": color,
                        "clusters": len(frame["clusters"]),
                        "tracks": len(frame["tracks"]),
                        "age_ms": age,
                        "stale": stale,
                    }
                )

            node_positions: List[Dict] = []
            if calib:
                for ki, nid in enumerate(calib.get("nodeIds", [])):
                    color = NODE_COLORS[ki % len(NODE_COLORS)]
                    if ki == 0:
                        node_positions.append(
                            {"node_id": nid, "x": 0, "y": 0, "color": color}
                        )
                    else:
                        try:
                            P = calib["P_opt"][0][ki]
                            node_positions.append(
                                {
                                    "node_id": nid,
                                    "x": round(P[0], 3),
                                    "y": round(P[1], 3),
                                    "color": color,
                                }
                            )
                        except Exception:
                            pass

            presence_list = [
                {
                    "node_id": nid,
                    "status": v["status"],
                    "color": NODE_COLORS[
                        (node_ids.index(nid) if nid in node_ids else 0)
                        % len(NODE_COLORS)
                    ],
                }
                for nid, v in self.presence.items()
            ]

            node_control = []
            stale_cutoff = now_ms - 2000
            for nid, ns in self.node_status.items():
                if ns.get("timestampMs", 0) < stale_cutoff:
                    continue
                node_control.append(
                    {
                        "node_id": nid,
                        "ip_address": self.node_ips.get(nid, "Unknown"),
                        "pipelineRunning": ns.get("pipelineRunning", False),
                        "triggerRunning": ns.get("triggerRunning", False),
                        "triggerMode": ns.get("triggerMode", ""),
                        "uptimeMs": ns.get("uptimeMs", 0),
                        "color": NODE_COLORS[
                            (node_ids.index(nid) if nid in node_ids else 0)
                            % len(NODE_COLORS)
                        ],
                    }
                )

            return {
                "timestampMs": now_ms,
                "calibrated": calib is not None,
                "calib_command_id": calib.get("commandId") if calib else None,
                "calibration": calib,   # NEW
                "node_ids": node_ids,
                "points": points,
                "tracks": tracks_list,
                "nodes_detail": nodes_detail,
                "node_positions": node_positions,
                "presence": presence_list,
                "node_control": node_control,
            }


state = State()

# ---------------------------------------------------------------------------
# Calibration UI state (module-level, accessed by Socket.IO handlers)
# ---------------------------------------------------------------------------
_mqtt_client: Optional[mqtt.Client] = None
_node_statuses: Dict[str, dict] = {}  # node_id -> {pipelineRunning, uptimeMs, ...}
_calib_active = False
_calib_command_id: Optional[str] = None
_calib_frames_req = 150
_calib_group_id = "default"
_calib_start_ms = 0


def _build_calib_state() -> dict:
    elapsed = (
        int(time.time() * 1000) - _calib_start_ms
        if _calib_active and _calib_start_ms
        else 0
    )
    return {
        "active": _calib_active,
        "commandId": _calib_command_id,
        "framesReq": _calib_frames_req,
        "groupId": _calib_group_id,
        "elapsedMs": elapsed,
    }


# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------


def _build_mqtt() -> mqtt.Client:
    c = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id="dashboard", clean_session=True
    )
    if MQTT_USER:
        c.username_pw_set(MQTT_USER, MQTT_PASS)

    def on_connect(client, userdata, flags, rc, props):
        if rc != 0:
            log.error("MQTT connect failed  rc=%s", rc)
            return
        log.info("MQTT connected  %s:%s", MQTT_HOST, MQTT_PORT)
        client.subscribe(f"{TOPIC_PREFIX}/group/+/frames/+", qos=0)
        client.subscribe(f"{TOPIC_PREFIX}/group/+/calibration/result", qos=1)
        client.subscribe(f"{TOPIC_PREFIX}/presence/+", qos=1)
        client.subscribe(f"{TOPIC_PREFIX}/server/start/result", qos=1)
        client.subscribe(f"{TOPIC_PREFIX}/group/+/node/+/status", qos=1)

    def on_message(client, userdata, msg):
        global _calib_active, _calib_command_id
        try:
            p = json.loads(msg.payload.decode()) if msg.payload else {}
        except json.JSONDecodeError:
            return
        parts = msg.topic.split("/")
        if "/frames/" in msg.topic:
            node_id = parts[-1]
            group_id = parts[3]
            is_new = node_id not in state.frames
            
            state.update_frame(node_id, p)
            
            if is_new:
                # Request status the first time we see frames from this node
                cmd_topic = f"{TOPIC_PREFIX}/group/{group_id}/node/{node_id}/command"
                cmd_payload = {"action": "status", "timestampMs": int(time.time() * 1000)}
                client.publish(cmd_topic, payload=json.dumps(cmd_payload), qos=1)
                log.info("First frame seen for %s, requested status.", node_id)
                
        elif msg.topic == f"{TOPIC_PREFIX}/server/start/result":
            if not p.get("ok", False):
                _calib_active = False
                _calib_command_id = None
                log.info("Calibration rejected  reason=%s", p.get("reason"))
        elif "/calibration/result" in msg.topic:
            if getattr(msg, "retain", False):
                return
            state.update_calibration(p)
            # Mark calibration as done when result arrives
            _calib_active = False
            _calib_command_id = p.get("commandId")
        elif "/node/" in msg.topic and "/status" in msg.topic:
            state.update_node_status(parts[5], p)
        elif msg.topic.startswith(f"{TOPIC_PREFIX}/presence/"):
            node_id = parts[-1]
            was_offline = state.presence.get(node_id, {}).get("status") != "online"
            is_online = p.get("status") == "online"
            
            state.update_presence(node_id, p)
            
            if was_offline and is_online:
                # Request status when node explicitly announces it is online
                cmd_topic = f"{TOPIC_PREFIX}/group/default/node/{node_id}/command"
                cmd_payload = {"action": "status", "timestampMs": int(time.time() * 1000)}
                client.publish(cmd_topic, payload=json.dumps(cmd_payload), qos=1)
                log.info("Node %s came online, requested status.", node_id)

    c.on_connect = on_connect
    c.on_message = on_message
    return c


# ---------------------------------------------------------------------------
# Web server
# ---------------------------------------------------------------------------

sio = socketio.AsyncServer(async_mode="aiohttp", cors_allowed_origins="*")
app = web.Application()
sio.attach(app)

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
jinja = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))

async def _fetch_ips_from_db():
    """Background task to periodically fetch node IPs from Postgres and map to DNS names."""
    while True:
        try:
            conn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                user=DB_USER, password=DB_PASS, connect_timeout=3
            )
            with conn.cursor() as cur:
                cur.execute("SELECT node_id, ip_address FROM node_status")
                rows = cur.fetchall()
                with state._lock:
                    for row in rows:
                        nid = row[0]
                        ip = row[1] if len(row) > 1 else None
                        # replace stored ip with a hostname preference (nodeX) when resolvable
                        state.node_ips[nid] = _choose_hostname(nid, ip)
            conn.close()
        except Exception as e:
            log.warning("Could not fetch IPs from DB: %s", e)
        await asyncio.sleep(5)  # Update IPs every 5 seconds

@sio.event
async def connect(sid, environ):
    log.info("Browser connected  sid=%s", sid)
    await sio.emit("calib_state", _build_calib_state(), to=sid)
    await sio.emit(
        "mqtt_status",
        {
            "host": MQTT_HOST,
            "port": MQTT_PORT,
            "user": MQTT_USER or "(anonymous)",
            "connected": _mqtt_client is not None and _mqtt_client.is_connected(),
        },
        to=sid,
    )


@sio.event
async def disconnect(sid):
    log.info("Browser disconnected  sid=%s", sid)


@sio.event
async def start_calibration(sid, data):
    """Trigger calibration from the debug UI."""
    global \
        _calib_active, \
        _calib_command_id, \
        _calib_frames_req, \
        _calib_group_id, \
        _calib_start_ms

    if _mqtt_client is None:
        await sio.emit(
            "calib_state", {"active": False, "error": "MQTT not connected"}, to=sid
        )
        return

    group_id = str(data.get("groupId", "default")).strip()
    frames = int(data.get("calibrationFrames", 150))
    command_id = f"cmd-{uuid.uuid4().hex[:12]}"

    topic = f"{TOPIC_PREFIX}/server/start/request"
    payload = {
        "schemaVersion": 1,
        "timestampMs": int(time.time() * 1000),
        "requestId": f"req-{uuid.uuid4().hex[:8]}",
        "groupId": group_id,
        "commandId": command_id,
        "captureConfig": {
            "calibration": True,
            "calibrationFrames": frames,
        },
    }
    _mqtt_client.publish(topic, payload=json.dumps(payload), qos=1)

    _calib_active = True
    _calib_command_id = command_id
    _calib_frames_req = frames
    _calib_group_id = group_id
    _calib_start_ms = int(time.time() * 1000)

    log.info(
        "Calibration triggered  group=%s  frames=%d  commandId=%s",
        group_id,
        frames,
        command_id,
    )
    await sio.emit("calib_state", _build_calib_state())


@sio.event
async def node_command(sid, data):
    """Send pipeline command to a specific node."""
    log.info("node_command RECEIVED  data=%s", json.dumps(data))
    if _mqtt_client is None:
        log.error("node_command: _mqtt_client is None")
        return
    node_id = str(data.get("nodeId", ""))
    group_id = str(data.get("groupId", "default"))
    action = str(data.get("action", "status"))
    topic = f"{TOPIC_PREFIX}/group/{group_id}/node/{node_id}/command"
    payload = {"action": action, "timestampMs": int(time.time() * 1000)}
    info = _mqtt_client.publish(topic, payload=json.dumps(payload), qos=1)
    log.info(
        "Node command  node=%s  action=%s  topic=%s  rc=%s  mid=%s",
        node_id,
        action,
        topic,
        info.rc,
        info.mid,
    )


async def node_command_handler(request):
    """HTTP fallback for node commands — publishes to MQTT directly."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid json"}, status=400)
    if _mqtt_client is None:
        return web.json_response(
            {"ok": False, "error": "mqtt not connected"}, status=503
        )
    node_id = str(body.get("nodeId", ""))
    group_id = str(body.get("groupId", "default"))
    action = str(body.get("action", "status"))
    topic = f"{TOPIC_PREFIX}/group/{group_id}/node/{node_id}/command"
    payload = {"action": action, "timestampMs": int(time.time() * 1000)}
    info = _mqtt_client.publish(topic, payload=json.dumps(payload), qos=1)
    log.info(
        "HTTP command  node=%s  action=%s  topic=%s  rc=%s",
        node_id,
        action,
        topic,
        info.rc,
    )
    return web.json_response({"ok": True, "rc": info.rc})


async def index_handler(request):
    tmpl = jinja.get_template("debug.html")
    return web.Response(text=tmpl.render(), content_type="text/html")


async def status_handler(request):
    return web.Response(text="UP", content_type="text/plain")


app.router.add_post("/api/node_command", node_command_handler)
app.router.add_get("/", index_handler)
app.router.add_get("/status", status_handler)

# new periodic task to request node status so update_node_status gets refreshed
async def _periodic_status_request():
    """Periodically request status from known nodes so `update_node_status` is kept up-to-date."""
    while True:
        try:
            with state._lock:
                # prefer the set of nodes we've seen frames/presence for, fallback to node_ips keys
                nodes = set(state.frames.keys()) | set(state.presence.keys()) | set(state.node_ips.keys())
            for nid in nodes:
                topic = f"{TOPIC_PREFIX}/group/default/node/{nid}/command"
                payload = {"action": "status", "timestampMs": int(time.time() * 1000)}
                if _mqtt_client is not None:
                    _mqtt_client.publish(topic, payload=json.dumps(payload), qos=1)
            # run every 10 seconds
        except Exception as exc:
            log.warning("Periodic status request failed: %s", exc)
        await asyncio.sleep(10)


async def _broadcast():
    while True:
        try:
            snap = state.snapshot()
            await sio.emit("debug_frame", snap)
            await sio.emit("calib_state", _build_calib_state())
        except Exception as exc:
            log.warning("Broadcast error: %s", exc)
        await asyncio.sleep(1 / 30)


async def _on_startup(app_):
    app_["broadcast"] = asyncio.create_task(_broadcast())
    app_["db_poll"] = asyncio.create_task(_fetch_ips_from_db())
    app_["status_req"] = asyncio.create_task(_periodic_status_request())


async def _on_cleanup(app_):
    app_["broadcast"].cancel()
    app_["db_poll"].cancel()
    app_["status_req"].cancel()
    try:
        await app_["broadcast"]
        await app_["db_poll"]
        await app_["status_req"]
    except asyncio.CancelledError:
        pass


app.on_startup.append(_on_startup)
app.on_cleanup.append(_on_cleanup)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    global _mqtt_client
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [DASH] %(levelname)s %(message)s"
    )
    _mqtt_client = _build_mqtt()
    try:
        _mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    except Exception as exc:
        log.error("MQTT connect error: %s", exc)
    _mqtt_client.loop_start()
    log.info("Dashboard starting on http://0.0.0.0:%d", DASHBOARD_PORT)
    web.run_app(app, host="0.0.0.0", port=DASHBOARD_PORT, access_log=None)
    _mqtt_client.loop_stop()
    _mqtt_client.disconnect()


if __name__ == "__main__":
    main()
