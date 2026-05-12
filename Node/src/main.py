import os
import signal
import sys
import socket
from multiprocessing import Process, Queue

# Local imports
from .radar import config
from .radar.daq_new import DataAcquisition
from .radar.pipeline import daq_process, processing_process, socket_process, calibration_mqtt_process

# ================= CONFIG =================
SERVER_URL = os.getenv("SERVER_URL", "http://127.0.0.1:5001")
NODE_ID = os.getenv("NODE_ID", socket.gethostname())
GROUP_ID = os.getenv("GROUP_ID", "default")

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", NODE_ID)
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")

RAW_QUEUE_SIZE = 5
PROCESSED_QUEUE_SIZE = 2
CALIB_QUEUE_SIZE = 200          # frames buffered for calibration publishing
VISUALIZE_CLUSTERS_ONLY = True  # set False to see raw RDM heatmap
# =========================================

def main():
    processes = []

    def signal_handler(sig, frame):
        print("\nShutting down...")
        for p in processes:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Create queues
    raw_queue = Queue(maxsize=RAW_QUEUE_SIZE)
    processed_queue = Queue(maxsize=PROCESSED_QUEUE_SIZE)
    calib_queue = Queue(maxsize=CALIB_QUEUE_SIZE)

    p_daq = Process(
        target=daq_process,
        args=(raw_queue, DataAcquisition),
        name="DAQ",
    )

    p_proc = Process(
        target=processing_process,
        args=(raw_queue, processed_queue, NODE_ID),
        kwargs={
            "calib_queue": calib_queue,
            "visualize_clusters_only": VISUALIZE_CLUSTERS_ONLY,
            "guard_cells_doppler": 4,
            "guard_cells_range": 16,
            "training_cells_doppler": 6,
            "training_cells_range": 24,
            "threshold_factor": 2,
            "pad_doppler": 18,
            "pad_range": 50,
        },
        name="Processing",
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

    p_calib = Process(
        target=calibration_mqtt_process,
        args=(calib_queue, NODE_ID, GROUP_ID, MQTT_HOST, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD),
        name="CalibPublisher",
    )

    processes.extend([p_daq, p_proc, p_sock, p_calib])
    print(f"Node {NODE_ID} started. Connecting to {SERVER_URL}, MQTT broker {MQTT_HOST}:{MQTT_PORT}")

    for p in processes:
        p.start()

    for p in processes:
        p.join()

if __name__ == "__main__":
    main()
