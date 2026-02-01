import os
import time

import numpy as np
import socketio
from new_pipe.cfar import cfar_pytorch
from new_pipe.rdm import RangeDoppler

SERVER_URL = "http://127.0.0.1:5000"


def main(rdm):
    # read frame from frame.txt

    frame = np.loadtxt(
        os.path.join(os.path.dirname(__file__), "data", "daq-cpp.txt"), dtype=np.uint16
    )
    rdm.set_buffer(frame)
    frame1 = rdm.process()

    frame2 = np.loadtxt(
        os.path.join(os.path.dirname(__file__), "data", "rdm-cpp.txt"), dtype=np.uint8
    )
    print(frame2[:100])

    return frame1, frame2


def reconnect_socketio():
    sio = socketio.Client()
    try:
        sio.connect(SERVER_URL)
        print("[SOCKET] Connected")
        return sio
    except Exception as e:
        print("[SOCKET] Connect failed:", e)
        return None


if __name__ == "__main__":
    rdm = RangeDoppler()
    rdm.process()
    frame1, frame2 = main(rdm)

    sio = None
    frame1 = frame1.reshape(64, 512)
    frame2 = frame2.reshape(64, 512)
    print(frame1.dtype)
    print(frame2.dtype)
    for i in range(100):
        if sio is None or not sio.connected:
            sio = reconnect_socketio()
        try:
            print(frame2.shape)
            sio.emit(
                "send_frame",
                {
                    "array": frame1[:, :256].tobytes(),
                },
            )
        except Exception as e:
            print("[SOCKET] Send error:", e)
            sio = None
        time.sleep(0.2)
