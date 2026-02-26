import os
import signal
import sys
import socket
from multiprocessing import Process, Queue

# Local imports
from .radar import config
from .radar.daq import DataAcquisition
from .radar.calibration import CalibrationManager
from .radar.pipeline import daq_process, processing_process, socket_process

# ================= CONFIG =================
SERVER_URL = os.getenv("SERVER_URL", "http://127.0.0.1:5001")
NODE_ID = os.getenv("NODE_ID", socket.gethostname())
RAW_QUEUE_SIZE = 5
PROCESSED_QUEUE_SIZE = 2
# =========================================

def main():
    # Signal handling
    def signal_handler(sig, frame):
        print("\nShutting down...")
        p_daq.terminate()
        p_proc.terminate()
        p_sock.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Create queues
    raw_queue = Queue(maxsize=RAW_QUEUE_SIZE)
    processed_queue = Queue(maxsize=PROCESSED_QUEUE_SIZE)

    # Create processes
    # DAQ Process
    p_daq = Process(
        target=daq_process, 
        args=(raw_queue, DataAcquisition), 
        name="DAQ"
    )
    
    # Processing Process
    p_proc = Process(
        target=processing_process, 
        args=(raw_queue, processed_queue, NODE_ID), 
        kwargs={
            'guard_cells_doppler': 4,
            'guard_cells_range': 16,
            'training_cells_doppler': 6,
            'training_cells_range': 24,
            'threshold_factor': 2,
            'pad_doppler': 18,
            'pad_range': 50
        },
        name="Processing"
    )
    
    # Socket Process
    p_sock = Process(
        target=socket_process, 
        args=(processed_queue, SERVER_URL, NODE_ID), 
        name="Socket"
    )

    print(f"Node {NODE_ID} started. Connecting to {SERVER_URL}")

    # Start processes
    p_daq.start()
    p_proc.start()
    p_sock.start()

    # Wait for completion
    p_daq.join()
    p_proc.join()
    p_sock.join()

if __name__ == "__main__":
    main()
