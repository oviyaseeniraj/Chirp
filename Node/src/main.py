#!/usr/bin/env python3
"""
Chirp  –  Radar pipeline entry point
=====================================
Launches the full processing chain: DAQ → Processing → Post-DBSCAN → Socket + MQTT.

The UI server and hardware trigger are expected to already be running
(managed by node_launcher.py or run_tests.sh).

Usage
-----
  python3 -m src.main          (when NODE_DIR is on PYTHONPATH)
  python3 src/main.py          (when running from NODE_DIR directly)

Env vars (honours NODE_DIR/.env):
  MQTT_HOST, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD
  NODE_ID, GROUP_ID, SERVER_URL
"""

from __future__ import annotations

import os
import signal
import socket
import sys
from multiprocessing import Process, Queue

# ---- Imports (relative when run as a module, absolute when run as a script) ----
try:
    from .radar.daq_new import DataAcquisition
    from .radar.pipeline_updated import (
        daq_process,
        post_dbscan_process,
        processing_process,
        socket_process,
    )
except ImportError:
    # Fallback for direct execution (python3 src/main.py)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.radar.daq_new import DataAcquisition  # type: ignore[assignment]
    from src.radar.pipeline_updated import (  # type: ignore[assignment]
        daq_process,
        post_dbscan_process,
        processing_process,
        socket_process,
    )

# ---------------------------------------------------------------------------
# Configuration (env vars with sensible defaults — node_launcher propagates)
# ---------------------------------------------------------------------------
SERVER_URL = os.getenv("SERVER_URL", "http://127.0.0.1:5001")
NODE_ID = os.getenv("NODE_ID", socket.gethostname())
GROUP_ID = os.getenv("GROUP_ID", "default")

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
print(MQTT_HOST)
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", NODE_ID)
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")

RAW_QUEUE_SIZE = 5
DBSCAN_QUEUE_SIZE = 5
PROCESSED_QUEUE_SIZE = 2
VISUALIZE_CLUSTERS_ONLY = False


# ---------------------------------------------------------------------------
def main() -> None:
    processes: list[Process] = []

    def _signal_handler(sig: int, frame: object) -> None:
        print("\nShutting down...")
        for p in processes:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # --- Queues ---
    raw_queue: Queue = Queue(maxsize=RAW_QUEUE_SIZE)
    dbscan_queue: Queue = Queue(maxsize=DBSCAN_QUEUE_SIZE)
    processed_queue: Queue = Queue(maxsize=PROCESSED_QUEUE_SIZE)

    # --- Pipeline processes ---
    p_daq = Process(
        target=daq_process,
        args=(raw_queue, DataAcquisition),
        name="DAQ",
    )

    p_proc = Process(
        target=processing_process,
        args=(raw_queue, dbscan_queue, NODE_ID),
        name="Processing",
    )

    p_post_dbscan = Process(
        target=post_dbscan_process,
        args=(dbscan_queue, processed_queue, NODE_ID),
        kwargs={
            "visualize_clusters_only": VISUALIZE_CLUSTERS_ONLY,
        },
        name="PostDBSCAN",
    )

    p_sock = Process(
        target=socket_process,
        args=(processed_queue, SERVER_URL, NODE_ID),
        kwargs={
            "group_id": GROUP_ID,
            "mqtt_host": MQTT_HOST,
            "mqtt_port": MQTT_PORT,
            "mqtt_user": MQTT_USERNAME,
            "mqtt_pass": MQTT_PASSWORD,
        },
        name="Socket",
    )

    processes = [p_daq, p_proc, p_post_dbscan, p_sock]

    print(
        f"Pipeline starting  node={NODE_ID}  group={GROUP_ID}  "
        f"server={SERVER_URL}  mqtt={MQTT_HOST}:{MQTT_PORT}"
    )

    for p in processes:
        p.start()

    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        print("Interrupted — stopping pipeline...")
    finally:
        for p in processes:
            p.terminate()
        print("Pipeline stopped")


if __name__ == "__main__":
    main()
