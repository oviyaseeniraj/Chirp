import mmap
import time
from multiprocessing import Process

import numpy as np
import posix_ipc
from cfar import cfar_pytorch
from new_pipe.daq import DataAcquisition
from new_pipe.rdm import RangeDoppler

# Shared memory settings
SHM_NAME = "/frame_shm"
SEM_EMPTY_NAME = "/frame_empty"
SEM_FULL_NAME = "/frame_full"
FRAME_SHAPE = (64, 512)
FRAME_SIZE = FRAME_SHAPE[0] * FRAME_SHAPE[1] * 4 * 3 * 2  # float32 = 4 bytes


def setup_shared_memory():
    # Open or create shared memory
    shm = posix_ipc.SharedMemory(SHM_NAME, posix_ipc.O_CREAT, size=FRAME_SIZE)
    mm = mmap.mmap(shm.fd, shm.size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
    shm.close_fd()
    # Open or create semaphores
    sem_empty = posix_ipc.Semaphore(SEM_EMPTY_NAME, posix_ipc.O_CREAT, initial_value=1)
    sem_full = posix_ipc.Semaphore(SEM_FULL_NAME, posix_ipc.O_CREAT, initial_value=0)
    return mm, sem_empty, sem_full


def producer():
    mm, sem_empty, sem_full = setup_shared_memory()
    daq = DataAcquisition()
    try:
        frame_count = 0
        while True:
            # Wait for empty slot
            sem_empty.acquire()
            frame = daq.process()
            print(len(frame))
            mm.seek(0)
            mm.write(frame.tobytes())
            print(f"[Producer] Wrote frame {frame_count}")
            frame_count += 1
            sem_full.release()
    except KeyboardInterrupt:
        pass
    finally:
        mm.close()


def consumer():
    mm, sem_empty, sem_full = setup_shared_memory()
    rdm = RangeDoppler()
    try:
        frame_count = 0
        while True:
            # Wait for full slot
            sem_full.acquire()

            # Read frame
            mm.seek(0)
            frame = np.frombuffer(mm.read(FRAME_SIZE), dtype=np.float32).reshape(
                FRAME_SHAPE
            )

            rdm.set_buffer(frame)
            frame = rdm.process().reshape(64, 512).astype(np.float32)

            # Signal empty slot
            sem_empty.release()

            # Run CFAR
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

            print(f"[Consumer] Processed frame {frame_count}")
            frame_count += 1

    except KeyboardInterrupt:
        pass
    finally:
        mm.close()


if __name__ == "__main__":
    # Start producer and consumer as separate processes
    p_prod = Process(target=producer)
    p_cons = Process(target=consumer)

    p_prod.start()
    p_cons.start()

    try:
        p_prod.join()
        p_cons.join()
    except KeyboardInterrupt:
        print("Stopping processes...")
    finally:
        # Cleanup
        try:
            posix_ipc.Semaphore(SEM_EMPTY_NAME).unlink()
            posix_ipc.Semaphore(SEM_FULL_NAME).unlink()
            posix_ipc.SharedMemory(SHM_NAME).unlink()
        except Exception:
            pass
