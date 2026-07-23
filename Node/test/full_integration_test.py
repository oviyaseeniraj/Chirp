import multiprocessing as mp
import os
import socket
import sys

# Add parent directory to path to import src modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


try:
    from src.radar.daq_new import DataAcquisition
    from src.radar.pipeline_updated import (
        daq_process,
        post_dbscan_process,
        processing_process,
        socket_process,
    )
except ImportError:
    from ..src.radar.daq_new import DataAcquisition
    from ..src.radar.pipeline_updated import (
        daq_process,
        post_dbscan_process,
        processing_process,
        socket_process,
    )

# Configuration
SERVER_URL = os.getenv("SERVER_URL", "http://127.0.0.1:5001")
NODE_ID = os.getenv("NODE_ID", socket.gethostname())
GROUP_ID = os.getenv("GROUP_ID", "default")
MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", NODE_ID)
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")


def main():
    # Create queues
    raw_queue = mp.Queue(maxsize=5)
    processed_queue = mp.Queue(maxsize=2)
    dbscan_queue = mp.Queue(maxsize=2)

    # Create processes using modular components
    p_daq = mp.Process(
        target=daq_process, args=(raw_queue, DataAcquisition), name="DAQ"
    )

    p_proc = mp.Process(
        target=processing_process,
        args=(raw_queue, dbscan_queue, NODE_ID),
        name="Processing",
    )

    p_post_dbscan = mp.Process(
        target=post_dbscan_process,
        args=(dbscan_queue, processed_queue, NODE_ID),
        name="PostDBSCAN",
    )

    p_sock = mp.Process(
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

    # Start processes
    p_daq.start()
    p_proc.start()
    p_post_dbscan.start()
    p_sock.start()

    print(f"Full Integration Test started. Node: {NODE_ID}, Server: {SERVER_URL}")

    try:
        p_daq.join()
        p_proc.join()
        p_sock.join()
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        p_daq.terminate()
        p_proc.terminate()
        p_sock.terminate()
        print("Clean exit")


if __name__ == "__main__":
    main()
