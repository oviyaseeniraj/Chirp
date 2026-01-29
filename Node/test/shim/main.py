import mmap

import numpy as np
import posix_ipc
import socketio
from cfar import cfar_pytorch

# from supabase_manager import SupabaseFrameManager

# Open or create shared memory
shm = posix_ipc.SharedMemory("/frame_shm", posix_ipc.O_CREAT, size=64 * 512 * 4)
mm = mmap.mmap(shm.fd, shm.size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
shm.close_fd()  # fd no longer needed

# Open or create semaphores
sem_empty = posix_ipc.Semaphore("/frame_empty", posix_ipc.O_CREAT, initial_value=1)
sem_full = posix_ipc.Semaphore("/frame_full", posix_ipc.O_CREAT, initial_value=0)


def main(sio_plotter, sio_db, frame_count):
    # wait for producer to signal a frame is ready
    sem_full.acquire()

    # read frame (this is the Range-Doppler Map from the C++ producer)
    frame = np.frombuffer(mm, dtype=np.float32, count=64 * 512).reshape(64, 512).copy()

    # signal producer can write next frame
    sem_empty.release()
    cfar_data = cfar_pytorch(
        frame,
        pad_value=np.mean(frame[:, :256]),
        guard_cells_doppler=4,
        guard_cells_range=16,
        training_cells_doppler=6,
        training_cells_range=24,
        threshold_factor=2.5,
        pad_doppler=32,
        pad_range=128,
        device="cpu",
    )

    # Send to plotter server (for visualization)
    if sio_plotter and sio_plotter.connected:
        try:
            sio_plotter.emit(
                "send_frame", {"frame": frame.tolist(), "array": cfar_data.tolist()}
            )
        except Exception:
            pass

    # Send to database server (for storage)
    if sio_db and sio_db.connected:
        try:
            sio_db.emit(
                "store_frame", {"frame": frame.tolist()}
            )
        except Exception:
            pass

    return frame


def reconnect_socketio(host, port):
    """Try to reconnect to a Socket.IO server"""
    sio = socketio.Client()
    try:
        sio.connect(f"http://{host}:{port}")
        return sio
    except Exception:
        return None


if __name__ == "__main__":
    sio_plotter = None
    sio_db = None
    reconnect_attempts = 0
    max_reconnect_attempts = 5

    try:
        frame_count = 0
        while True:
            # Try to connect/reconnect plotter if needed
            if sio_plotter is None or not sio_plotter.connected:
                if reconnect_attempts < max_reconnect_attempts:
                    sio_plotter = reconnect_socketio("127.0.0.1", 5000)
                    if sio_plotter:
                        print("Connected to plotter server on port 5000")
                    reconnect_attempts += 1 if sio_plotter is None else 0
                else:
                    reconnect_attempts = 0

            # Try to connect/reconnect database if needed
            if sio_db is None or not sio_db.connected:
                sio_db = reconnect_socketio("127.0.0.1", 5001)
                if sio_db:
                    print("Connected to database server on port 5001")

            frame = main(sio_plotter, sio_db, frame_count)
            if frame is not None:
                frame_count += 1
                reconnect_attempts = 0  # Reset on successful frame

    except KeyboardInterrupt:
        pass
    except Exception:
        pass
    finally:
        # Cleanup
        if sio_plotter and sio_plotter.connected:
            sio_plotter.disconnect()
        if sio_db and sio_db.connected:
            sio_db.disconnect()
        mm.close()
        sem_empty.unlink()
        sem_full.unlink()
        shm.unlink()

