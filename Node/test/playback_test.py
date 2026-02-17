
import argparse
import multiprocessing as mp
import os
import signal
import sys
import time
import numpy as np

import psutil
import socketio
import torch

# Add parent directory to path to import src modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from src.radar import config
    from src.data_capture.playback import PlaybackDAQ
    from src.radar.processing.angle import angle_fft
    from src.radar.processing.cfar import cfar_pytorch
    from src.radar.processing.rdm import RangeDoppler
except ImportError:
    # If running from within Node/ with `python -m test.playback_test`
    from ..src.radar import config
    from ..src.data_capture.playback import PlaybackDAQ
    from ..src.radar.processing.angle import angle_fft
    from ..src.radar.processing.cfar import cfar_pytorch
    from ..src.radar.processing.rdm import RangeDoppler

# Configuration
SERVER_URL = "http://127.0.0.1:5001"

def daq_process(raw_queue, input_dir, loop, delay):
    """
    Process 0: Data Acquisition (Playback)
    Reads raw data from files and pushes to raw_queue
    """
    # Pin to core 0
    try:
        p = psutil.Process(os.getpid())
        p.cpu_affinity([0])
    except Exception as e:
        print(f"Could not pin DAQ process: {e}")

    print("Playback DAQ Process started")

    try:
        with PlaybackDAQ(input_dir, loop=loop, delay=delay) as daq:
            while True:
                try:
                    # Capture frame (from file)
                    frame_data = daq.capture()

                    # Push to queue (non-blocking, drop if full)
                    try:
                        # We copy just to be safe, though np.load usually returns new array
                        raw_queue.put_nowait(frame_data.copy())
                    except mp.queues.Full:
                        pass  # Drop frame if processing is too slow

                except Exception as e:
                    print(f"DAQ Error: {e}")
                    # If playback ends without loop, break
                    if "End of playback" in str(e):
                        print("Playback finished.")
                        break
                    time.sleep(0.1)
    except Exception as e:
        print(f"Failed to initialize PlaybackDAQ: {e}")


def processing_process(raw_queue, processed_queue):
    """
    Process 1: Signal Processing
    RDM -> CFAR -> Angle -> Output
    """
    # Pin to core 1
    try:
        p = psutil.Process(os.getpid())
        p.cpu_affinity([1])
    except Exception as e:
        print(f"Could not pin Processing process: {e}")

    print("Processing Process started")

    # Initialize Processing Modules
    rd = RangeDoppler(window="blackman")
    
    # Check for CUDA
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Processing using device: {device}")

    while True:
        try:
            # Get raw data
            frame_data = raw_queue.get()

            # 1. Range-Doppler Processing
            rd.set_buffer(frame_data)
            rmd_loss = rd.process()
            
            # 2. CFAR Detection
            clean_rdm = rd.get_clean_rdm()

            detections = cfar_pytorch(rmd_loss, device=device)

            # 3. Angle Estimation
            # Only if detections exist
            if detections.any():
                angles = angle_fft(detections, clean_rdm, device=device)
            else:
                angles = None

            # Pack output
            output_data = {
                "array": rmd_loss.tobytes(), # RDM image for background
                "cfar": detections.tobytes(),
                "angles": angles.tobytes() if angles is not None else None
            }

            try:
                processed_queue.put_nowait(output_data)
            except mp.queues.Full:
                pass

        except Exception as e:
            print(f"Processing Error: {e}")
            import traceback
            traceback.print_exc()


def socket_process(processed_queue):
    """
    Process 2: Socket Transmission
    Sends processed data to visualization server
    """
    print("Socket Process started")

    sio = socketio.Client()
    connected = False

    while True:
        try:
            if not connected:
                try:
                    sio.connect(SERVER_URL)
                    print(f"Connected to {SERVER_URL}")
                    connected = True
                except Exception:
                    time.sleep(1)
                    continue

            # Get processed data
            data = processed_queue.get()

            # Emit to server
            sio.emit("send_frame", data)
            
            # sio.sleep(0) # Yield

        except Exception as e:
            print(f"Socket Error: {e}")
            connected = False
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="Run playback test mimicking main pipeline.")
    parser.add_argument("--input-dir", required=True, help="Directory containing .npy raw frames")
    parser.add_argument("--loop", action="store_true", help="Loop playback indefinitely")
    parser.add_argument("--delay", type=float, default=0.1, help="Delay between frames (seconds)")
    args = parser.parse_args()

    # Set start method to spawn for better compatibility/safety
    # mp.set_start_method('spawn') 
    # 'fork' is faster on Linux and usually default.
    
    # Create queues
    raw_queue = mp.Queue(maxsize=10)
    processed_queue = mp.Queue(maxsize=10)

    # Create processes
    p_daq = mp.Process(target=daq_process, args=(raw_queue, args.input_dir, args.loop, args.delay), name="DAQ")
    p_proc = mp.Process(target=processing_process, args=(raw_queue, processed_queue), name="Processing")
    p_sock = mp.Process(target=socket_process, args=(processed_queue,), name="Socket")

    # Start processes
    p_daq.start()
    p_proc.start()
    p_sock.start()

    print("All processes started")

    try:
        while True:
            time.sleep(1)
            # Check if processes are alive
            if not p_daq.is_alive():
                print("DAQ process finished/died!")
                break
            if not p_proc.is_alive():
                print("Processing process died!")
                break
            if not p_sock.is_alive():
                print("Socket process died!")
                break
                
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        p_daq.terminate()
        p_proc.terminate()
        p_sock.terminate()
        p_daq.join()
        p_proc.join()
        p_sock.join()
        print("Clean exit")


if __name__ == "__main__":
    main()
