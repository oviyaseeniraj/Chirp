import mmap
from threading import RLock

import numpy as np
import posix_ipc
import socketio
from cfar import cfar_pytorch
from new_pipe.rdm import RangeDoppler

# from supabase_manager import SupabaseFrameManager

# Open or create shared memory
# for raw data
# shm = posix_ipc.SharedMemory(
#     "/frame_shm", posix_ipc.O_CREAT, size=64 * 512 * 4 * 3 * 2 * 4
# )
# for rdm processed
# shm = posix_ipc.SharedMemory("/frame_shm", posix_ipc.O_CREAT, size=64 * 512 * 4)
# for just cube data
shm = posix_ipc.SharedMemory(
    "/frame_shm",
    posix_ipc.O_CREAT,
    size=64 * 512 * 4 * 3 * np.dtype(np.complex64).itemsize,
)

mm = mmap.mmap(shm.fd, shm.size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
shm.close_fd()  # fd no longer needed

# Open or create semaphores
sem_empty = posix_ipc.Semaphore("/frame_empty", posix_ipc.O_CREAT, initial_value=1)
sem_full = posix_ipc.Semaphore("/frame_full", posix_ipc.O_CREAT, initial_value=0)


def reconnect_socketio():
    """Try to reconnect to the plotter"""
    sio = socketio.Client()
    try:
        sio.connect("http://127.0.0.1:5000")  # Fixed port to 5000
        return sio
    except Exception:
        return None


def main(sio, frame_count, rdm):
    # wait for producer to signal a frame is ready
    sem_full.acquire()
    # read frame (this is the Range-Doppler Map from the C++ producer)
    frame_data = np.frombuffer(mm, dtype=np.complex64, count=64 * 512 * 4 * 3).copy()
    rdm.set_cube(frame_data)
    frame = rdm.rdm_process_cube().reshape(64, 512).astype(np.float32)
    print(frame.shape)

    # signal producer can write next frame
    sem_empty.release()

    # cfar_data = cfar_pytorch(
    #     frame,
    #     pad_value=np.mean(frame[:, :256]),
    #     guard_cells_doppler=4,
    #     guard_cells_range=16,
    #     training_cells_doppler=6,
    #     training_cells_range=24,
    #     threshold_factor=2.5,
    #     pad_doppler=32,
    #     pad_range=128,
    #     device="cpu",
    # )

    # need to add an angle fft to this

    if sio and sio.connected:
        try:
            sio.emit(
                "send_frame",
                {"frame": frame.tolist(), "array": frame[:, :256].tobytes()},
            )

        except Exception:
            # signal producer can write next frame even if send failed
            sem_empty.release()
            return None
    else:
        # Continue processing even without plotter connection
        pass

    return frame


if __name__ == "__main__":
    sio = None
    reconnect_attempts = 0
    max_reconnect_attempts = 5
    rdm = RangeDoppler()

    try:
        frame_count = 0
        while True:
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

    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(e)
        pass
    finally:
        # Cleanup
        if sio and sio.connected:
            sio.disconnect()
        mm.close()
        sem_empty.unlink()
        sem_full.unlink()
        shm.unlink()


# def main(rdm):
#     sem_full.acquire()
#     frame_data = np.frombuffer(mm, dtype=np.complex64, count=64 * 512 * 4 * 3).copy()
#     sem_empty.release()
#     rdm.set_cube(frame_data)
#     # rdm.process_frame_cube()


# if __name__ == "__main__":
#     rdm = RangeDoppler()

#     try:
#         while True:
#             main(rdm)

#     except KeyboardInterrupt:
#         pass
#     except Exception:
#         pass
#     finally:
#         mm.close()
#         sem_empty.unlink()
#         sem_full.unlink()
#         shm.unlink()
