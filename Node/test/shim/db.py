import logging
import threading
from queue import Queue

import numpy as np
from flask import Flask
from flask_socketio import SocketIO
from supabase_manager import SupabaseFrameManager

# Disable logging
logging.getLogger("werkzeug").disabled = True
logging.getLogger("socketio").disabled = True
logging.getLogger("engineio").disabled = True

app = Flask(__name__)
app.config["SECRET_KEY"] = "db-server"

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    logger=False,
    engineio_logger=False,
)


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

# Queue for background database writes
db_queue = Queue()


def database_writer_thread():
    """Background thread that writes frames to the database"""
    while True:
        try:
            frame_number, frame_data = db_queue.get()
            if frame_data is None:  # Sentinel to stop thread
                break
            
            if db_manager.is_ready():
                success = db_manager.store_frame(
                    rdm_frame=frame_data,
                    frame_number=frame_number,
                )
                if not success:
                    print(f"Warning: Failed to store frame {frame_number} to database")
                else:
                    if frame_number % 10 == 0:
                        print(f"Stored frame {frame_number} to database")
            else:
                print("Warning: Database manager not ready")
        except Exception as e:
            print(f"Error in database writer thread: {e}")


# Start background database writer thread
db_thread = threading.Thread(target=database_writer_thread, daemon=True)
db_thread.start()


@socketio.on("store_frame")
def handle_frame(data):
    """Listen for store_frame event from main.py and queue to database"""
    global frame_count

    try:
        if "frame" in data:
            frame_data = np.array(data["frame"], dtype=np.float32)
            frame_count += 1
            db_queue.put((frame_count, frame_data))
            print(f"Queued frame {frame_count} for database storage")
        else:
            print("Warning: No frame data in received frame")

    except Exception as e:
        print(f"Error processing frame: {e}")


if __name__ == "__main__":
    print("Starting database storage server...")
    print("Listening on 0.0.0.0:5001...")
    try:
        socketio.run(app, host="0.0.0.0", port=5001, debug=False)
    except KeyboardInterrupt:
        print("\nShutting down...")
        db_queue.put((None, None))
        db_thread.join(timeout=2)

