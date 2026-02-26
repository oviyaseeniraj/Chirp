import argparse
import multiprocessing as mp
import os
import sys

# Add parent directory to path to import src modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from src.data_capture.playback import PlaybackDAQ
    from src.radar.pipeline import daq_process, processing_process, socket_process
except ImportError:
    from ..src.data_capture.playback import PlaybackDAQ
    from ..src.radar.pipeline import daq_process, processing_process, socket_process

# Configuration
SERVER_URL = "http://127.0.0.1:5001"
NODE_ID = "playback_test_node"

def main():
    parser = argparse.ArgumentParser(description="Run playback test using modular pipeline.")
    parser.add_argument("--input-dir", required=True, help="Directory containing .npy raw frames")
    parser.add_argument("--loop", action="store_true", help="Loop playback indefinitely")
    parser.add_argument("--delay", type=float, default=0.1, help="Delay between frames (seconds)")
    parser.add_argument("--clusters-only", action="store_true", help="Visualize only clustered centroids (clean view)")
    args = parser.parse_args()

    # Create queues
    raw_queue = mp.Queue(maxsize=5)
    processed_queue = mp.Queue(maxsize=2)

    # Create processes using modular components
    p_daq = mp.Process(
        target=daq_process, 
        args=(raw_queue, PlaybackDAQ), 
        kwargs={'input_dir': args.input_dir, 'loop': args.loop, 'delay': args.delay},
        name="DAQ"
    )
    
    p_proc = mp.Process(
        target=processing_process, 
        args=(raw_queue, processed_queue, NODE_ID), 
        kwargs={'visualize_clusters_only': args.clusters_only},
        name="Processing"
    )
    
    p_sock = mp.Process(
        target=socket_process, 
        args=(processed_queue, SERVER_URL, NODE_ID), 
        name="Socket"
    )

    # Start processes
    p_daq.start()
    p_proc.start()
    p_sock.start()

    print(f"Playback started from {args.input_dir}. Processes: {p_daq.pid}, {p_proc.pid}, {p_sock.pid}")

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
