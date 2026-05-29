"""
Chirp MQTT → Postgres bridge
============================
Subscribes to the NanoMQ broker and persists every incoming message into the
appropriate Postgres table.

Topics consumed:
  chirp/v1/group/+/capture/start        → capture_commands
  chirp/v1/group/+/calibration/frame/+  → calibration_frames
  chirp/v1/group/+/calibration/done/+   → calibration_done
  chirp/v1/group/+/frames/+             → live_frames
"""

from __future__ import annotations

import json
import logging
import os
import sys

import paho.mqtt.client as mqtt
import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER") or None
MQTT_PASS = os.getenv("MQTT_PASS") or None

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "chirp")
DB_USER = os.getenv("DB_USER", "chirp")
DB_PASS = os.getenv("DB_PASS", "chirp")

TOPIC_PREFIX = "chirp/v1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BRIDGE] %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("bridge")

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _get_conn():
    """Return a new psycopg2 connection (autocommit)."""
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
    )
    conn.autocommit = True
    return conn


def _topic_parts(msg: mqtt.MQTTMessage) -> list[str]:
    """Split the topic string into segments, e.g.
    'chirp/v1/group/g1/frames/n1' → ['chirp','v1','group','g1','frames','n1']"""
    return msg.topic.split("/") if msg.topic else []


def _upsert_node_ip(conn, node_id: str, payload: dict) -> None:
    """Upserts the node's IP address if present in the payload."""
    ip_address = payload.get("ipAddress")
    if not ip_address:
        return

    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO node_status (node_id, ip_address, last_seen_ms)
            VALUES (%s, %s, %s)
            ON CONFLICT (node_id) DO UPDATE
            SET ip_address = EXCLUDED.ip_address,
                last_seen_ms = EXCLUDED.last_seen_ms
            """,
            (node_id, ip_address, payload.get("timestampMs", 0)),
        )
    except Exception as e:
        log.warning("Could not upsert node IP for %s: %s", node_id, e)
    finally:
        cursor.close()


# ---------------------------------------------------------------------------
# Per-topic insert handlers
# ---------------------------------------------------------------------------


def handle_capture_start(conn, topic_parts: list[str], payload: dict) -> None:
    """Store a capture/start command."""
    # chirp/v1/group/<groupId>/capture/start
    group_id = topic_parts[3]
    cfg = payload.get("captureConfig") or {}
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO capture_commands
            (group_id, command_id, calibration, calibration_frames,
             start_epoch_ms, target_node_ids, raw_payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            group_id,
            payload.get("commandId"),
            cfg.get("calibration", False),
            cfg.get("calibrationFrames", 150),
            payload.get("startEpochMs"),
            json.dumps(payload.get("targetNodeIds") or []),
            json.dumps(payload),
        ),
    )
    cursor.close()
    log.info(
        "capture/start  group=%s  commandId=%s", group_id, payload.get("commandId")
    )


def handle_calibration_frame(conn, topic_parts: list[str], payload: dict) -> None:
    """Store a single calibration frame."""
    # chirp/v1/group/<groupId>/calibration/frame/<nodeId>
    group_id = topic_parts[3]
    node_id = topic_parts[6]

    _upsert_node_ip(conn, node_id, payload)

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO calibration_frames
            (group_id, node_id, command_id, schema_version,
             timestamp_ms, frame_num, detections, tracks)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            group_id,
            node_id,
            payload.get("commandId"),
            payload.get("schemaVersion", 1),
            payload.get("timestampMs"),
            payload.get("frameNum"),
            json.dumps(payload.get("detections") or []),
            json.dumps(payload.get("tracks") or []),
        ),
    )
    cursor.close()
    log.debug(
        "calibration/frame  group=%s  node=%s  frameNum=%s",
        group_id,
        node_id,
        payload.get("frameNum"),
    )


def handle_calibration_done(conn, topic_parts: list[str], payload: dict) -> None:
    """Store a calibration-done signal."""
    # chirp/v1/group/<groupId>/calibration/done/<nodeId>
    group_id = topic_parts[3]
    node_id = topic_parts[6]
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO calibration_done
            (group_id, node_id, command_id, schema_version,
             timestamp_ms, total_frames)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            group_id,
            node_id,
            payload.get("commandId"),
            payload.get("schemaVersion", 1),
            payload.get("timestampMs"),
            payload.get("totalFrames"),
        ),
    )
    cursor.close()
    log.info(
        "calibration/done  group=%s  node=%s  totalFrames=%s",
        group_id,
        node_id,
        payload.get("totalFrames"),
    )


def handle_live_frame(conn, topic_parts: list[str], payload: dict) -> None:
    """Store a live per-frame clusters + tracks message."""
    # chirp/v1/group/<groupId>/frames/<nodeId>
    group_id = topic_parts[3]
    node_id = topic_parts[5]

    _upsert_node_ip(conn, node_id, payload)

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO live_frames
            (group_id, node_id, schema_version, timestamp_ms, clusters, tracks)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            group_id,
            node_id,
            payload.get("schemaVersion", 1),
            payload.get("timestampMs"),
            json.dumps(payload.get("clusters") or []),
            json.dumps(payload.get("tracks") or []),
        ),
    )
    cursor.close()
    log.info("live/frames  group=%s  node=%s", group_id, node_id)


# ---------------------------------------------------------------------------
# MQTT callback
# ---------------------------------------------------------------------------


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        log.error("MQTT connect failed  reason_code=%s", reason_code)
        return

    # Subscribe to all four topic patterns
    subs = [
        f"{TOPIC_PREFIX}/group/+/capture/start",
        f"{TOPIC_PREFIX}/group/+/calibration/frame/+",
        f"{TOPIC_PREFIX}/group/+/calibration/done/+",
        f"{TOPIC_PREFIX}/group/+/frames/+",
    ]
    for topic in subs:
        client.subscribe(topic, qos=1)
        log.info("Subscribed  topic=%s", topic)

    log.info("Bridge connected to MQTT broker at %s:%s", MQTT_HOST, MQTT_PORT)


def on_message(client, userdata, msg):
    conn = userdata["db_conn"]

    try:
        payload = json.loads(msg.payload.decode()) if msg.payload else {}
    except json.JSONDecodeError:
        log.warning("Skipping non-JSON message on topic=%s", msg.topic)
        return

    parts = _topic_parts(msg)
    if len(parts) < 5:
        log.warning("Unexpected topic shape  topic=%s", msg.topic)
        return

    try:
        subtype = parts[4]  # "capture" | "calibration" | "frames"

        if subtype == "capture":
            handle_capture_start(conn, parts, payload)
        elif subtype == "calibration":
            subsub = parts[5]  # "frame" or "done"
            if subsub == "frame":
                handle_calibration_frame(conn, parts, payload)
            elif subsub == "done":
                handle_calibration_done(conn, parts, payload)
            else:
                log.warning("Unknown calibration subtopic  parts=%s", parts)
        elif subtype == "frames":
            handle_live_frame(conn, parts, payload)
        else:
            log.warning("Unknown subtype  topic=%s", msg.topic)

    except Exception:
        log.exception("Failed to persist message  topic=%s", msg.topic)
        # Attempt to reconnect to the database on next message
        try:
            conn.reset()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    # Wait for Postgres to be ready (up to 30 s)
    import time

    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            db_conn = _get_conn()
            db_conn.close()
            log.info("Postgres is ready")
            break
        except psycopg2.OperationalError:
            log.info("Waiting for Postgres …")
            time.sleep(2)
    else:
        log.error("Postgres did not become ready; exiting")
        sys.exit(1)

    db_conn = _get_conn()

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="chirp-bridge",
        clean_session=True,
        userdata={"db_conn": db_conn},
    )
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_forever()


if __name__ == "__main__":
    main()
