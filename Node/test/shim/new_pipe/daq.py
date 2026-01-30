import socket
import struct
import time
from array import array

# Constants from main.h
FAST_TIME = 512
SLOW_TIME = 64
RX = 4
TX = 3
IQ = 2
IQ_BYTES = 2
SIZE_W_IQ = TX * RX * FAST_TIME * SLOW_TIME * IQ
BUFFER_SIZE = 2048
PORT = 4098
BYTES_IN_PACKET = 1456


class DataAcquisition:
    def __init__(self):
        self.frame = 0
        self.packets_read = 0
        # Allocate buffers
        # uint16_t equivalent
        self.frame_data = array("H", [0] * SIZE_W_IQ)
        self.buffer = bytearray(BUFFER_SIZE)
        # Calculate sizes
        self.BYTES_IN_FRAME = SLOW_TIME * FAST_TIME * RX * TX * IQ * IQ_BYTES
        self.BYTES_IN_FRAME_CLIPPED = (
            self.BYTES_IN_FRAME // BYTES_IN_PACKET
        ) * BYTES_IN_PACKET
        self.UINT16_IN_PACKET = BYTES_IN_PACKET // 2
        self.sockfd = None
        self.cliaddr = None

        # Pre-create struct format for unpacking
        self._struct_format = f"<{self.UINT16_IN_PACKET}H"
        self._struct_size = struct.calcsize(self._struct_format)

    def create_bind_socket(self):
        self.sockfd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sockfd.bind(("", PORT))

    def close_socket(self):
        if self.sockfd is not None:
            self.sockfd.close()
            self.sockfd = None

    def read_socket(self):
        data, self.cliaddr = self.sockfd.recvfrom(BUFFER_SIZE)
        self.buffer[: len(data)] = data
        return len(data)

    def set_frame_data(self):
        base_index = self.UINT16_IN_PACKET * self.packets_read

        # Use struct.unpack_from for fast byte-to-uint16 conversion
        unpacked = struct.unpack_from(self._struct_format, self.buffer, 10)

        # Bulk assignment using slice
        self.frame_data[base_index : base_index + self.UINT16_IN_PACKET] = array(
            "H", unpacked
        )

        self.packets_read += 1

    def end_of_frame(self):
        byte_mod = (self.packets_read * BYTES_IN_PACKET) % self.BYTES_IN_FRAME_CLIPPED
        return byte_mod == 0

    def process(self):
        start = time.perf_counter_ns()
        self.create_bind_socket()
        while True:
            self.read_socket()
            self.set_frame_data()
            if self.end_of_frame():
                self.packets_read = 0
                self.close_socket()
                break
        stop = time.perf_counter_ns()
        duration_us = (stop - start) // 1_000
        print(f"Frame {self.frame}: {duration_us} μs")
        self.frame += 1
        return self.frame_data

    def get_frame_count(self):
        return self.frame
