import socket
import struct
import time
from array import array
from enum import CONTINUOUS
from logging import currentframe
from sys import gettotalrefcount

import numpy as np

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
UINT64_MAX = np.iinfo(np.uint64).max


class DataAcquisition:
    def __init__(self):
        self.frame = 0
        self.packets_read = 0
        # Allocate buffers
        # uint16_t equivalent - use numpy for better performance and matching C behavior
        self.frame_data = np.zeros(SIZE_W_IQ, dtype=np.uint16)
        self.buffer = bytearray(BUFFER_SIZE)
        # Calculate sizes
        self.BYTES_IN_FRAME = SLOW_TIME * FAST_TIME * RX * TX * IQ * IQ_BYTES
        self.BYTES_IN_FRAME_CLIPPED = (
            self.BYTES_IN_FRAME // BYTES_IN_PACKET
        ) * BYTES_IN_PACKET
        self.UINT16_IN_PACKET = BYTES_IN_PACKET // 2
        self.sockfd = None
        self.cliaddr = None

    def __del__(self):
        self.close_socket()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_socket()
        return False

    # added buffer size and an extra check
    def create_bind_socket(self):
        if self.sockfd is None:
            try:
                # increase the size of the socket buffer to 8MB
                self.sockfd = socket.socket(
                    socket.AF_INET, socket.SOCK_DGRAM, 8 * 1024 * 1024
                )
                self.sockfd.bind(("", PORT))
            except socket.error as e:
                print(f"Socket creation failed: {e}")
                self.sockfd = None

    def close_socket(self):
        if self.sockfd is not None:
            print("closed")
            self.sockfd.close()
            self.sockfd = None

    def read_socket(self):
        data, self.cliaddr = self.sockfd.recvfrom(BUFFER_SIZE)
        self.buffer[: len(data)] = data
        return len(data)

    def set_frame_data(self):
        base_index = self.UINT16_IN_PACKET * self.packets_read

        # Use numpy's frombuffer which respects native byte order
        # This reads 728 uint16 values starting from byte 10
        data_view = np.frombuffer(
            self.buffer, dtype=np.uint16, count=self.UINT16_IN_PACKET, offset=10
        )

        # Copy to frame_data
        self.frame_data[base_index : base_index + self.UINT16_IN_PACKET] = data_view

        self.packets_read += 1

    # added get packet num
    def get_packet_num(self):
        packet_num = np.frombuffer(self.buffer, dtype=np.uint32, count=1, offset=0)[0]
        return packet_num

    # added get byte count
    def get_byte_count(self):
        byte_count = int.from_bytes(memoryview(self.buffer)[4:10], "little")
        return byte_count

    def place_packet_payload_into_frame(self, slot):
        payloadBytes = BYTES_IN_PACKET
        dst_u16 = (slot * payloadBytes) // 2
        data_view = np.frombuffer(
            self.buffer, dtype=np.uint16, count=self.UINT16_IN_PACKET, offset=10
        )
        self.frame_data[dst_u16 : dst_u16 + self.UINT16_IN_PACKET] = data_view

    def end_of_frame(self):
        byte_mod = (self.packets_read * BYTES_IN_PACKET) % self.BYTES_IN_FRAME_CLIPPED
        return byte_mod == 0

    def process_v2(self):
        # timer
        start = time.perf_counter_ns()
        # socket
        self.create_bind_socket
        # inits
        currFrameId = UINT64_MAX
        # frame processing
        got = np.zeros((self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET), dtype=np.uint8)
        gotCount = 0
        duplicates = 0
        while True:
            nbytes = self.read_socket()

            # timeout or err
            if nbytes < 0:
                currFrameId = UINT64_MAX
                got[:] = 0
                gotCount = 0
                duplicates = 0

            # header + payload
            if nbytes < (10 + BYTES_IN_PACKET):
                continue

            pktNum = self.get_packet_num()
            bc = self.get_byte_count()

            frameId = bc // self.BYTES_IN_FRAME_CLIPPED
            offset = bc % self.BYTES_IN_FRAME_CLIPPED
            slot = offset // frameId

            # first packet arrived
            if currFrameId == np.iinfo(np.uint64).max:
                currFrameId = frameId
                got[:] = 0
                gotCount = 0
                duplicates = 0
                self.frame_data[:] = 0

            # out of order
            if frameId < currFrameId:
                continue

            if frameId > currFrameId:
                missing = (self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET) - gotCount
                currFrameId = frameId
                got[:] = 0
                gotCount = 0
                duplicates = 0
                self.frame_data[:] = 0

            if (slot < 0) or (slot >= self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET):
                continue

            if got[slot]:
                duplicates += 1

            self.place_packet_payload_into_frame(slot)
            got[slot] = 1
            gotCount += 1

            if gotCount == self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET:
                break

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
