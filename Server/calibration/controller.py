"""
Chirp  –  Calibration controller
=================================
MQTT service that orchestrates multi-node self-calibration.

Flow
----
1. Laptop publishes  chirp/v1/server/start/request  (calibration=true)
2. Controller selects active nodes, publishes  chirp/v1/group/<gid>/capture/start
3. Nodes stream  chirp/v1/group/<gid>/calibration/frame/<nid>
4. Each node sends  chirp/v1/group/<gid>/calibration/done/<nid>
5. When all nodes are done the controller runs closed-form calibration
6. Result published to  chirp/v1/group/<gid>/calibration/result
7. Result also persisted to Postgres
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import paho.mqtt.client as mqtt
import psycopg2
from calibration import closed_form_calibration

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 1
TOPIC_PREFIX = "chirp/v1"

START_REQUEST_TOPIC = f"{TOPIC_PREFIX}/server/start/request"
START_RESULT_TOPIC = f"{TOPIC_PREFIX}/server/start/result"
SERVER_STATUS_TOPIC = f"{TOPIC_PREFIX}/server/status"
PRESENCE_TOPIC = f"{TOPIC_PREFIX}/presence/+"
STATE_TOPIC = f"{TOPIC_PREFIX}/group/+/capture/state/+"
ACK_TOPIC = f"{TOPIC_PREFIX}/group/+/capture/ack/+"
CALIB_FRAME_TOPIC = f"{TOPIC_PREFIX}/group/+/calibration/frame/+"
CALIB_DONE_TOPIC = f"{TOPIC_PREFIX}/group/+/calibration/done/+"

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
MQTT_HOST = os.getenv("MQTT_HOST", "nanomq")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER") or os.getenv("MQTT_SERVER_USER") or None
MQTT_PASS = os.getenv("MQTT_PASS") or os.getenv("MQTT_SERVER_PASS") or None
CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "chirp-calibration")

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "chirp")
DB_USER = os.getenv("DB_USER", "chirp")
DB_PASS = os.getenv("DB_PASS", "chirp")

PRESENCE_STALE_MS = int(os.getenv("CHIRP_PRESENCE_STALE_MS", "6000"))
STATE_STALE_MS = int(os.getenv("CHIRP_STATE_STALE_MS", "10000"))
ACK_TIMEOUT_MS = int(os.getenv("CHIRP_ACK_TIMEOUT_MS", "5000"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CALIB-CTL] %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("calibration.controller")


def _now_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CalibrationSession:
    command_id: str
    group_id: str
    target_nodes: Set[str]
    frame_data: Dict[str, Dict[int, List]] = field(default_factory=dict)
    done_nodes: Set[str] = field(default_factory=set)
    created_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    lock: threading.Lock = field(default_factory=threading.Lock)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class CalibrationController:
    def __init__(self) -> None:
        # Node tracking
        self.presence: Dict[str, Dict[str, Any]] = {}
        self.state: Dict[tuple, Dict[str, Any]] = {}
        self.presence_lock = threading.Lock()
        self.state_lock = threading.Lock()

        # Calibration sessions: commandId -> CalibrationSession
        self.sessions: Dict[str, CalibrationSession] = {}
        self.sessions_lock = threading.Lock()

        self.shutdown = threading.Event()

        # DB connection (lazy)
        self._db_conn = None

        # MQTT
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=CLIENT_ID,
            clean_session=False,
        )
        if MQTT_USER:
            self.client.username_pw_set(MQTT_USER, MQTT_PASS)

        # LWT — server status
        self.client.will_set(
            SERVER_STATUS_TOPIC,
            payload=json.dumps(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "serverId": CLIENT_ID,
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

    # ----- DB helpers ---------------------------------------------------

    def _get_db(self):
        if self._db_conn is None or self._db_conn.closed:
            self._db_conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASS,
            )
            self._db_conn.autocommit = True
        return self._db_conn

    def _persist_result(self, payload: dict) -> None:
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """CREATE TABLE IF NOT EXISTS calibration_results (
                    id          BIGSERIAL PRIMARY KEY,
                    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    group_id    TEXT NOT NULL,
                    command_id  TEXT NOT NULL,
                    ok          BOOLEAN NOT NULL,
                    reason      TEXT,
                    node_ids    JSONB,
                    P_opt       JSONB,
                    theta_opt   JSONB,
                    solve_meta  JSONB,
                    raw_payload JSONB NOT NULL
                )""",
            )
            cur.execute(
                """INSERT INTO calibration_results
                   (group_id, command_id, ok, reason, node_ids, P_opt, theta_opt, solve_meta, raw_payload)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    payload.get("groupId"),
                    payload.get("commandId"),
                    payload.get("ok"),
                    payload.get("reason"),
                    json.dumps(payload.get("nodeIds")),
                    json.dumps(payload.get("P_opt")),
                    json.dumps(payload.get("theta_opt")),
                    json.dumps(payload.get("solveMeta") or {}),
                    json.dumps(payload),
                ),
            )
            cur.close()
            log.info(
                "Persisted calibration result to DB  commandId=%s",
                payload.get("commandId"),
            )
        except Exception:
            log.exception("Failed to persist result to DB")

    # ----- MQTT callbacks -----------------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            log.error("MQTT connect failed  rc=%s", reason_code)
            return

        subs = [
            START_REQUEST_TOPIC,
            PRESENCE_TOPIC,
            STATE_TOPIC,
            ACK_TOPIC,
            CALIB_FRAME_TOPIC,
            CALIB_DONE_TOPIC,
        ]
        for t in subs:
            client.subscribe(t, qos=1)
            log.info("Subscribed  %s", t)

        client.publish(
            SERVER_STATUS_TOPIC,
            payload=json.dumps(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "serverId": CLIENT_ID,
                    "status": "online",
                    "timestampMs": _now_ms(),
                }
            ),
            qos=1,
            retain=True,
        )

        log.info("Calibration controller online  broker=%s:%s", MQTT_HOST, MQTT_PORT)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        if self.shutdown.is_set():
            log.info("Disconnected from broker (shutdown)")
        else:
            log.warning("Unexpected disconnect  rc=%s", reason_code)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode()) if msg.payload else {}
        except json.JSONDecodeError:
            return

        topic = msg.topic

        if topic == START_REQUEST_TOPIC:
            threading.Thread(
                target=self._handle_start_request, args=(payload,), daemon=True
            ).start()
        elif topic.startswith(f"{TOPIC_PREFIX}/presence/"):
            self._handle_presence(topic, payload)
        elif "/capture/state/" in topic:
            self._handle_state(topic, payload)
        elif "/capture/ack/" in topic:
            self._handle_ack(topic, payload)
        elif "/calibration/frame/" in topic:
            self._handle_calib_frame(topic, payload)
        elif "/calibration/done/" in topic:
            self._handle_calib_done(topic, payload)

    # ----- Presence & state tracking ------------------------------------

    def _handle_presence(self, topic: str, payload: dict) -> None:
        node_id = topic.split("/")[-1]
        with self.presence_lock:
            self.presence[node_id] = {"payload": payload, "updatedMs": _now_ms()}

    def _handle_state(self, topic: str, payload: dict) -> None:
        parts = topic.split("/")
        if len(parts) < 7:
            return
        group_id, node_id = parts[3], parts[-1]
        with self.state_lock:
            self.state[(group_id, node_id)] = {
                "payload": payload,
                "updatedMs": _now_ms(),
            }

    def _handle_ack(self, topic: str, payload: dict) -> None:
        # ACKs are logged for observability; the real flow uses
        # _wait_for_acks for the active command lifecycle.
        parts = topic.split("/")
        if len(parts) < 7:
            return
        node_id, command_id = parts[-1], str(payload.get("commandId", ""))
        log.info(
            "ACK  node=%s  commandId=%s  ready=%s",
            node_id,
            command_id,
            payload.get("ready"),
        )

    # ----- Start request → calibration trigger --------------------------

    def _handle_start_request(self, payload: dict) -> None:
        group_id = str(payload.get("groupId", "")).strip()
        capture_cfg = payload.get("captureConfig", {}) or {}
        is_calib = capture_cfg.get("calibration", False)

        if not group_id:
            self._publish_result(
                ok=False, reason="missing_group_id", request_id=payload.get("requestId")
            )
            return

        # Select nodes that are online and in this group
        selected = self._select_active_nodes(group_id)
        if not selected and not is_calib:
            self._publish_result(
                ok=False,
                reason="no_active_nodes",
                request_id=payload.get("requestId"),
                group_id=group_id,
            )
            return
        if not selected and is_calib:
            log.info("No presence nodes — broadcasting calibration to all subscribers")

        # Delay
        lead_ms = int(os.getenv("CHIRP_LEAD_TIME_MS", "5000"))
        start_epoch_ms = _now_ms() + lead_ms
        command_id = f"cmd-{uuid.uuid4().hex[:12]}"

        # Publish capture/start to all targeted nodes
        start_topic = f"{TOPIC_PREFIX}/group/{group_id}/capture/start"
        start_payload = {
            "schemaVersion": SCHEMA_VERSION,
            "timestampMs": _now_ms(),
            "groupId": group_id,
            "commandId": command_id,
            "startEpochMs": start_epoch_ms,
            "captureConfig": capture_cfg,
        }
        if selected:
            start_payload["targetNodeIds"] = sorted(selected)
            start_payload["expectedNodeCount"] = len(selected)
        self.client.publish(start_topic, payload=json.dumps(start_payload), qos=1)
        log.info(
            "Published capture/start  commandId=%s  group=%s  targets=%s",
            command_id,
            group_id,
            sorted(selected),
        )

        # If calibration mode, create a session for collecting frames
        if is_calib:
            session = CalibrationSession(
                command_id=command_id,
                group_id=group_id,
                target_nodes=set(selected),
            )
            with self.sessions_lock:
                self.sessions[command_id] = session
            log.info(
                "Calibration session created  commandId=%s  nodes=%s",
                command_id,
                sorted(selected),
            )

        # Acknowledge the laptop
        self._publish_result(
            ok=True,
            reason="command_dispatched",
            request_id=payload.get("requestId"),
            group_id=group_id,
            extras={"commandId": command_id, "targetNodeIds": sorted(selected)},
        )

    def _select_active_nodes(self, group_id: str) -> Set[str]:
        now_ms = _now_ms()
        active: Set[str] = set()

        with self.presence_lock:
            psnap = dict(self.presence)
        with self.state_lock:
            ssnap = dict(self.state)

        for node_id, rec in psnap.items():
            if now_ms - int(rec.get("updatedMs", 0)) > PRESENCE_STALE_MS:
                continue
            if rec.get("payload", {}).get("status") != "online":
                continue
            if str(rec.get("payload", {}).get("groupId", "")) != group_id:
                continue

            sr = ssnap.get((group_id, node_id))
            if sr is not None:
                if now_ms - int(sr.get("updatedMs", 0)) <= STATE_STALE_MS:
                    st = str(sr.get("payload", {}).get("state", ""))
                    if st in {"error", "offline"}:
                        continue
            active.add(node_id)
        return active

    def _publish_result(
        self,
        ok: bool,
        reason: str,
        request_id: Optional[str] = None,
        group_id: Optional[str] = None,
        extras: Optional[dict] = None,
    ) -> None:
        payload: dict = {
            "schemaVersion": SCHEMA_VERSION,
            "timestampMs": _now_ms(),
            "requestId": request_id,
            "groupId": group_id,
            "ok": ok,
            "reason": reason,
        }
        if extras:
            payload.update(extras)
        self.client.publish(START_RESULT_TOPIC, payload=json.dumps(payload), qos=1)
        log.info("Published result  ok=%s  reason=%s  group=%s", ok, reason, group_id)

    # ----- Calibration frame collection ---------------------------------

    def _handle_calib_frame(self, topic: str, payload: dict) -> None:
        parts = topic.split("/")
        if len(parts) < 7:
            return
        node_id = parts[-1]
        command_id = str(payload.get("commandId", ""))
        frame_num = payload.get("frameNum")
        tracks = payload.get("tracks", [])

        if not command_id or frame_num is None:
            return

        with self.sessions_lock:
            session = self.sessions.get(command_id)
        if session is None:
            return

        with session.lock:
            if node_id not in session.frame_data:
                session.frame_data[node_id] = {}
            session.frame_data[node_id][int(frame_num)] = tracks

    def _handle_calib_done(self, topic: str, payload: dict) -> None:
        parts = topic.split("/")
        if len(parts) < 7:
            return
        node_id = parts[-1]
        command_id = str(payload.get("commandId", ""))
        total_frames = payload.get("totalFrames", 0)

        if not command_id:
            return

        with self.sessions_lock:
            session = self.sessions.get(command_id)
        if session is None:
            log.warning("Done for unknown commandId=%s  node=%s", command_id, node_id)
            return

        with session.lock:
            session.done_nodes.add(node_id)
            log.info(
                "Calib done  node=%s  commandId=%s  frames=%d  (%d/%d)",
                node_id,
                command_id,
                total_frames,
                len(session.done_nodes),
                len(session.target_nodes),
            )

            all_done = session.done_nodes >= session.target_nodes

        if all_done:
            threading.Thread(
                target=self._run_calibration, args=(session,), daemon=True
            ).start()

    # ----- Calibration solver -------------------------------------------

    def _run_calibration(self, session: CalibrationSession) -> None:
        with session.lock:
            snapshot = {nid: dict(frames) for nid, frames in session.frame_data.items()}
            command_id = session.command_id
            group_id = session.group_id

        log.info(
            "Running calibration  commandId=%s  nodes=%s",
            command_id,
            sorted(snapshot.keys()),
        )

        node_ids, P_opt, theta_opt, solve_meta = closed_form_calibration(snapshot)

        result_topic = f"{TOPIC_PREFIX}/group/{group_id}/calibration/result"

        if node_ids is None:
            reason = (solve_meta or {}).get("reason", "calibration_failed")
            result = {
                "schemaVersion": SCHEMA_VERSION,
                "timestampMs": _now_ms(),
                "groupId": group_id,
                "commandId": command_id,
                "ok": False,
                "reason": reason,
                "nodeIds": sorted(snapshot.keys()),
                "solveMeta": solve_meta,
            }
        else:

            def _serialize_complex(mat):
                return [[[float(v.real), float(v.imag)] for v in row] for row in mat]

            result = {
                "schemaVersion": SCHEMA_VERSION,
                "timestampMs": _now_ms(),
                "groupId": group_id,
                "commandId": command_id,
                "ok": True,
                "reason": "calibration_complete",
                "nodeIds": node_ids,
                "P_opt": _serialize_complex(P_opt),
                "theta_opt": theta_opt.tolist(),
                "solveMeta": solve_meta,
            }

        self.client.publish(result_topic, payload=json.dumps(result), qos=1)
        log.info(
            "Calibration result published  commandId=%s  ok=%s  topic=%s",
            command_id,
            result["ok"],
            result_topic,
        )

        self._persist_result(result)

        with self.sessions_lock:
            self.sessions.pop(command_id, None)

    # ----- Run ----------------------------------------------------------

    def run(self) -> None:
        # Wait for DB
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                c = self._get_db()
                c.close()
                self._db_conn = None
                log.info("Database ready")
                break
            except Exception:
                log.info("Waiting for database …")
                time.sleep(2)
        else:
            log.error("Database not ready; exiting")
            sys.exit(1)

        self.client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        self.client.loop_start()

        log.info("Calibration controller running  clientId=%s", CLIENT_ID)
        self.shutdown.wait()

        self.client.loop_stop()
        self.client.disconnect()
        log.info("Calibration controller stopped")


if __name__ == "__main__":
    ctl = CalibrationController()
    # Graceful shutdown on SIGTERM / SIGINT
    import signal as _signal

    _signal.signal(_signal.SIGTERM, lambda *_: ctl.shutdown.set())
    _signal.signal(_signal.SIGINT, lambda *_: ctl.shutdown.set())
    ctl.run()
