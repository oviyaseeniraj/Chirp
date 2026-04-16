import gc
import socket
import time
import numpy as np
from . import config

class DataAcquisition:
    def __init__(self, debug_level=1):
        """
        Initialize DataAcquisition
        
        Args:
            debug_level: 0=silent, 1=errors/warnings only, 2=info, 3=verbose debug
        """
        self.debug_level = debug_level
        self.frame = 0
        self.packets_read = 0
        
        # Constants from config
        self.BYTES_IN_PACKET = config.BYTES_IN_PACKET
        self.BYTES_IN_FRAME_CLIPPED = config.BYTES_IN_FRAME_CLIPPED
        self.UINT16_IN_PACKET = self.BYTES_IN_PACKET // 2
        
        # Allocate buffers
        # uint16_t equivalent - use numpy for better performance and matching C behavior
        self.frame_data = np.zeros(config.BYTES_IN_FRAME // 2, dtype=np.int16) # Size in uint16
        self.buffer = bytearray(config.BUFFER_SIZE)
        
        self.sockfd = None
        self.cliaddr = None
        self.first_frame_captured = False

    def __del__(self):
        self.close_socket()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_socket()
        return False

    def create_bind_socket(self):
        if self.sockfd is None:
            try:
                # increase the size of the socket buffer to 8MB
                print("trying to make socket")
                self.sockfd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sockfd.setsockopt(
                    socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024 * 1024
                )
                self.sockfd.settimeout(0.5)
                self.sockfd.bind(("", config.PORT))
                print("socket made")
            except socket.error as e:
                print(f"Socket creation failed: {e}")
                self.sockfd = None

    def close_socket(self):
        if self.sockfd is not None:
            self.sockfd.close()
            self.sockfd = None

    def capture(self, timeout=None):
        """
        ABSOLUTE MAXIMUM PERFORMANCE - Nuclear option.
        formerly process_v6
        
        Args:
            timeout (float, optional): Seconds to wait for a frame before raising TimeoutError.
                                     If None, wait indefinitely (default behavior).
        """

        # Setup
        if self.sockfd is None:
            self.create_bind_socket()

        # Constants - computed once
        P = self.BYTES_IN_FRAME_CLIPPED // self.BYTES_IN_PACKET  # packets per frame
        F = self.BYTES_IN_FRAME_CLIPPED  # frame bytes
        U = self.UINT16_IN_PACKET  # uint16 per packet
        B = self.BYTES_IN_PACKET  # bytes per packet
        UINT64_MAX = np.iinfo(np.uint64).max

        # State
        c = UINT64_MAX  # current frame
        g = np.zeros(P, dtype=np.uint8)  # got
        n = 0  # count
        f = -1  # first slot

        # Refs
        d = self.frame_data
        b = self.buffer
        s = self.sockfd

        # Disable GC
        e = gc.isenabled()
        gc.disable()

        start_time = time.time()

        try:
            while True:
                # Check for timeout
                if timeout is not None:
                    if (time.time() - start_time) > timeout:
                        raise TimeoutError(f"Timed out waiting for frame data after {timeout}s")

                # Zero-copy receive
                try:
                    z, _ = s.recvfrom_into(b, config.BUFFER_SIZE)
                except socket.timeout:
                    # Socket timeout allows checking the loop condition (and our overall timeout)
                    # It resets the partial frame state, which is correct for UDP
                    c = UINT64_MAX
                    g[:] = 0
                    n = 0
                    f = -1
                    continue
                except Exception:
                    c = UINT64_MAX
                    g[:] = 0
                    n = 0
                    f = -1
                    continue

                # Size check
                if z < 1466:
                    continue

                # Parse byte_count - direct bit operations (fastest)
                x = (
                    b[4]
                    | (b[5] << 8)
                    | (b[6] << 16)
                    | (b[7] << 24)
                    | (b[8] << 32)
                    | (b[9] << 40)
                )

                # Compute
                i = x // F  # frame id
                j = (x % F) // B  # slot

                # State machine - optimized for sequential packets in same frame
                if i == c:
                    # FAST PATH: same frame
                    if j < P and not g[j]:
                        k = (j * B) >> 1
                        d[k : k + U] = np.frombuffer(b, np.int16, U, 10)
                        g[j] = 1
                        n += 1
                        if n == P:
                            if f == 0 or self.first_frame_captured:
                                self.first_frame_captured = True
                                break
                            c = UINT64_MAX
                            g[:] = 0
                            n = 0
                            f = -1
                elif c == UINT64_MAX:
                    # Initialize
                    c = i
                    g[:] = 0
                    n = 0
                    f = j
                    d[:] = 0
                    if j < P:
                        k = (j * B) >> 1
                        d[k : k + U] = np.frombuffer(b, np.int16, U, 10)
                        g[j] = 1
                        n = 1
                elif i > c:
                    # New frame
                    if (
                        self.first_frame_captured
                        and n < P - (P >> 2)
                        and self.debug_level
                    ):
                        print(f"[!] {c}: {n}/{P}")
                    c = i
                    g[:] = 0
                    n = 0
                    f = j
                    d[:] = 0
                    if j < P:
                        k = (j * B) >> 1
                        d[k : k + U] = np.frombuffer(b, np.int16, U, 10)
                        g[j] = 1
                        n = 1
                # else: i < c, ignore old packet

            return d
        finally:
            if e:
                gc.enable()
