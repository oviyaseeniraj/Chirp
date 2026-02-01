import mmap
import time

import numpy as np
import posix_ipc
import socketio
from new_pipe.cfar import cfar_pytorch
from new_pipe.rdm import RangeDoppler

SIZE_W_IQ = 64 * 512 * 4 * 3 * 2

# from supabase_manager import SupabaseFrameManager

# Open or create shared memory
shm = posix_ipc.SharedMemory("/frame_shm", posix_ipc.O_CREAT, size=SIZE_W_IQ * 2)
# shm = posix_ipc.SharedMemory("/frame_shm", posix_ipc.O_CREAT, size=64 * 512 * 4)
mm = mmap.mmap(shm.fd, shm.size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
shm.close_fd()  # fd no longer needed

# Open or create semaphores
sem_empty = posix_ipc.Semaphore("/frame_empty", posix_ipc.O_CREAT, initial_value=1)
sem_full = posix_ipc.Semaphore("/frame_full", posix_ipc.O_CREAT, initial_value=0)


def main(sio, frame_count, rdm):
    # wait for producer to signal a frame is ready
    sem_full.acquire()
    # read frame (this is the Range-Doppler Map from the C++ producer)
    frame_data = np.frombuffer(mm, dtype=np.uint16, count=SIZE_W_IQ).copy()
    rdm.set_buffer(frame_data)
    frame = rdm.process().reshape(64, 512).astype(np.uint8)
    #
    # frame = np.frombuffer(mm, dtype=np.float32, count=64 * 512).reshape(64, 512).copy()

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

    # need to add an angle fft to this
    if sio and sio.connected:
        try:
            sio.emit(
                "send_frame",
                {"array": frame[:, :256].tobytes()},
            )

        except Exception as e:
            # signal producer can write next frame even if send failed
            print(e)
            sem_empty.release()
            return None
    else:
        # Continue processing even without plotter connection
        print("not connected")
        pass

    return frame


def reconnect_socketio():
    """Try to reconnect to the plotter"""
    sio = socketio.Client()
    try:
        sio.connect("http://127.0.0.1:5000")  # Fixed port to 5000
        return sio
    except Exception:
        return None


if __name__ == "__main__":
    sio = None
    reconnect_attempts = 0
    max_reconnect_attempts = 5
    rdm = RangeDoppler()

    try:
        frame_count = 0
        while True:
            start = time.perf_counter_ns()

            # Try to connect/reconnect if needed
            if sio is None or not sio.connected:
                if reconnect_attempts < max_reconnect_attempts:
                    sio = reconnect_socketio()
                    reconnect_attempts += 1 if sio is None else 0
                else:
                    reconnect_attempts = 0  # Reset for future attempts
            frame = main(sio, frame_count, rdm)
            if frame is not None:
                frame_count += 1
                reconnect_attempts = 0  # Reset on successful frame
            end = time.perf_counter_ns()
            print(f"Processing time: {(end - start) / 1e6:.2f} ms")

    except KeyboardInterrupt:
        pass
    except Exception:
        pass
    finally:
        # Cleanup
        if sio and sio.connected:
            sio.disconnect()
        mm.close()
        sem_empty.unlink()
        sem_full.unlink()
        shm.unlink()
