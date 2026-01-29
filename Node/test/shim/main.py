import mmap

import numpy as np
import posix_ipc
import socketio
from cfar import cfar_pytorch

# Open or create shared memory for RDM data
shm = posix_ipc.SharedMemory("/frame_shm", posix_ipc.O_CREAT, size=64 * 512 * 4)
mm = mmap.mmap(shm.fd, shm.size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
shm.close_fd()  # fd no longer needed

# Open or create shared memory for DAQ frame data
# Size: TX * RX * FAST_TIME * SLOW_TIME * IQ = 3 * 4 * 512 * 64 * 2 = 786,432 uint16_t elements
# Each uint16_t is 2 bytes, so total size = 786432 * 2 = 1,572,864 bytes
shm_daq = posix_ipc.SharedMemory("/daq_frame_shm", posix_ipc.O_CREAT, size=3 * 4 * 512 * 64 * 2 * 2)
mm_daq = mmap.mmap(shm_daq.fd, shm_daq.size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
shm_daq.close_fd()

# Open or create semaphores
sem_empty = posix_ipc.Semaphore("/frame_empty", posix_ipc.O_CREAT, initial_value=1)
sem_full = posix_ipc.Semaphore("/frame_full", posix_ipc.O_CREAT, initial_value=0)

# Semaphores for DAQ frame data
sem_daq_empty = posix_ipc.Semaphore("/daq_frame_empty", posix_ipc.O_CREAT, initial_value=1)
sem_daq_full = posix_ipc.Semaphore("/daq_frame_full", posix_ipc.O_CREAT, initial_value=0)


def main(sio):
    # wait for producer to signal a frame is ready
    sem_full.acquire()

    # read RDM frame
    frame = np.frombuffer(mm, dtype=np.float32, count=64 * 512).reshape(64, 512).copy()

    # signal producer can write next frame
    sem_empty.release()
    
    # wait for DAQ frame to be ready
    sem_daq_full.acquire()
    
    # read DAQ frame - shape: (TX=3, RX=4, FAST_TIME=512, SLOW_TIME=64, IQ=2)
    daq_frame = np.frombuffer(mm_daq, dtype=np.uint16, count=3 * 4 * 512 * 64 * 2).reshape(3, 4, 512, 64, 2).copy()
    
    # signal producer can write next DAQ frame
    sem_daq_empty.release()
    
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

    if sio and sio.connected:
        try:
            sio.emit("send_array", {"array": cfar_data.tolist()})
        except Exception:
            pass
    else:
        # Continue processing even without plotter connection
        pass

    return frame, daq_frame


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

            result = main(sio)
            if result is not None:
                frame, daq_frame = result
                frame_count += 1
                reconnect_attempts = 0  # Reset on successful frame
                
                # Save DAQ frame data to file for later algorithm processing
                # TODO: modify this to save to a database instead
                np.save(f"daq_frame_{frame_count}.npy", daq_frame)

    except KeyboardInterrupt:
        pass
    except Exception:
        pass
    finally:
        # Cleanup
        if sio and sio.connected:
            sio.disconnect()
        mm.close()
        mm_daq.close()
        sem_empty.unlink()
        sem_full.unlink()
        sem_daq_empty.unlink()
        sem_daq_full.unlink()
        shm.unlink()
        shm_daq.unlink()
