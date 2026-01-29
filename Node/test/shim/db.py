import logging

import numpy as np
import socketio
from supabase_manager import SupabaseFrameManager

# Disable logging
logging.getLogger("socketio").disabled = True
logging.getLogger("engineio").disabled = True


def init_db():
    db_manager = SupabaseFrameManager()
    if not db_manager.is_ready():
        raise SystemExit(
            "Supabase not ready. Check SUPABASE_URL and SUPABASE_SERVICE_KEY."
        )
    return db_manager


# Initialize database manager globally
db_manager = init_db()
frame_count = 0

# Create Socket.IO client
sio = socketio.Client(logger=False, engineio_logger=False)


@sio.event
def connect():
    print("Connected to Socket.IO server on port 5000")


@sio.event
def disconnect():
    print("Disconnected from Socket.IO server")


@sio.on("send_frame")
def handle_frame(data):
    """Listen for send_frame event from main.py and store to Supabase database"""
    global frame_count

    try:
        # Print JSON structure (keys only, not data)
        print(f"Received data with keys: {list(data.keys())}")

        # Extract image data if it's in the fast_plot format
        # Or handle raw array data
        if "array" in data:
            array_data = np.array(data["array"], dtype=np.float32)
        else:
            print("Warning: No array data in received frame")
            return

        if "frame" in data:
            frame_data = np.array(data["frame"], dtype=np.float32)
        else:
            print("Warning: No frame data in received frame")
            return

        frame_count += 1

        # Store Range-Doppler Map frame to Supabase database
        if db_manager.is_ready():
            success = db_manager.store_frame(
                rdm_frame=frame_data,
                frame_number=frame_count,
                # Note: Additional metadata like range_value, angle_value, etc.
                # could be passed here if available from C++ producer
            )
            if not success:
                print(f"Warning: Failed to store frame {frame_count} to database")
            else:
                if frame_count % 10 == 0:  # Print every 10th frame to reduce spam
                    print(f"Stored frame {frame_count} to database")
        else:
            print("Warning: Database manager not ready")

    except Exception as e:
        print(f"Error processing frame: {e}")


if __name__ == "__main__":
    print("Starting database storage client...")
    print("Connecting to Socket.IO server at localhost:5000...")

    try:
        sio.connect("http://localhost:5000")
        sio.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        sio.disconnect()
    except Exception as e:
        print(f"Error: {e}")
