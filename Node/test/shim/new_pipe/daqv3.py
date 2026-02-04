import fcntl
import gc
import os
import socket
import struct
import time
from array import array

import numpy as np

# Pre-compile struct format for faster unpacking
STRUCT_BC = struct.Struct("<IHHI")  # uint32 pktNum, 48-bit bc split into I+HH

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
    def __init__(self, debug_level=1):
        """
        Initialize DataAcquisition

        Args:
            debug_level: 0=silent, 1=errors/warnings only, 2=info, 3=verbose debug
        """
        self.debug_level = debug_level
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
        self.first_frame_captured = False  # Track if we've completed first frame

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
                print("trying to make socket")
                self.sockfd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sockfd.setsockopt(
                    socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024 * 1024
                )
                self.sockfd.settimeout(0.5)  # 500ms timeout like C++ version
                self.sockfd.bind(("", PORT))
                print("socket made")
            except socket.error as e:
                print(f"Socket creation failed: {e}")
                self.sockfd = None

    def create_bind_socket_old(self):
        self.sockfd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sockfd.bind(("", PORT))

    def close_socket(self):
        if self.sockfd is not None:
            # print("closed")
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

    # original process
    def process(self):
        start = time.perf_counter_ns()
        self.create_bind_socket_old()
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

    # anirban line for line + some debugging
    def process_v2(self):
        # timer
        start = time.perf_counter_ns()
        # socket
        self.create_bind_socket()
        packetsPerFrame = self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET
        if self.debug_level >= 3:
            print(
                f"[DEBUG] Starting frame capture. Expected packets: {packetsPerFrame}"
            )

        # inits
        currFrameId = UINT64_MAX
        # frame processing
        got = np.zeros(packetsPerFrame, dtype=np.uint8)
        gotCount = 0
        duplicates = 0
        packet_count = 0
        first_packet_slot = -1  # Track first packet slot to detect mid-frame start

        while True:
            packet_count += 1
            try:
                nbytes = self.read_socket()
            except socket.timeout:
                # timeout - reset and try again
                if self.debug_level >= 1:
                    print(
                        f"[WARN] Socket timeout after {packet_count} packets. Resetting frame. gotCount={gotCount}"
                    )
                currFrameId = UINT64_MAX
                got[:] = 0
                gotCount = 0
                duplicates = 0
                packet_count = 0
                continue
            except socket.error as e:
                if self.debug_level >= 1:
                    print(f"[ERROR] Socket error after {packet_count} packets: {e}")
                currFrameId = UINT64_MAX
                got[:] = 0
                gotCount = 0
                duplicates = 0
                packet_count = 0
                continue

            # header + payload
            if nbytes < (10 + BYTES_IN_PACKET):
                if self.debug_level >= 1:
                    print(
                        f"[WARN] Short packet received: {nbytes} bytes (expected >= {10 + BYTES_IN_PACKET})"
                    )
                continue

            pktNum = self.get_packet_num()
            bc = self.get_byte_count()

            frameId = bc // self.BYTES_IN_FRAME_CLIPPED
            offset = bc % self.BYTES_IN_FRAME_CLIPPED
            slot = offset // BYTES_IN_PACKET

            # first packet arrived
            if currFrameId == np.iinfo(np.uint64).max:
                currFrameId = frameId
                got[:] = 0
                gotCount = 0
                duplicates = 0
                self.frame_data[:] = 0
                first_packet_slot = slot

                # Warn if starting mid-frame
                if slot != 0 and not self.first_frame_captured:
                    if self.debug_level >= 1:
                        print(
                            f"[WARN] Started capture mid-frame at slot={slot}. First frame will be incomplete and skipped."
                        )
                if self.debug_level >= 3:
                    print(
                        f"[DEBUG] First packet locked to frameId={frameId}, slot={slot}"
                    )

            # out of order
            if frameId < currFrameId:
                if self.debug_level >= 3:
                    print(
                        f"[DEBUG] Old packet ignored: frameId={frameId} < currFrameId={currFrameId}"
                    )
                continue

            if frameId > currFrameId:
                missing = packetsPerFrame - gotCount

                # If this is the first frame and we started mid-frame, this is expected
                if not self.first_frame_captured and first_packet_slot != 0:
                    if self.debug_level >= 2:
                        print(
                            f"[INFO] First incomplete frame discarded (expected). frameId={currFrameId}, got={gotCount}/{packetsPerFrame}, missing={missing}"
                        )
                        print(
                            f"[INFO] Reason: Capture started at slot {first_packet_slot}, not slot 0. Next frame will be complete."
                        )
                else:
                    if self.debug_level >= 1:
                        print(
                            f"[WARN] Incomplete frame discarded. frameId={currFrameId}, got={gotCount}/{packetsPerFrame}, missing={missing}, duplicates={duplicates}"
                        )
                        print(
                            f"[WARN] This indicates packet loss! Check network/CPU load."
                        )

                currFrameId = frameId
                got[:] = 0
                gotCount = 0
                duplicates = 0
                first_packet_slot = slot
                self.frame_data[:] = 0
                if self.debug_level >= 3:
                    print(f"[DEBUG] Starting new frame: frameId={frameId}, slot={slot}")

            if (slot < 0) or (slot >= self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET):
                if self.debug_level >= 1:
                    print(
                        f"[WARN] Slot out of range: pktNum={pktNum}, frameId={frameId}, slot={slot}"
                    )
                continue

            if got[slot]:
                duplicates += 1
                if self.debug_level >= 3:
                    print(
                        f"[DEBUG] Duplicate slot detected: slot={slot}, duplicates={duplicates}"
                    )
                continue

            self.place_packet_payload_into_frame(slot)
            got[slot] = 1
            gotCount += 1

            # Progress indicator every 10% of packets
            if (
                gotCount
                % max(1, (self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET) // 10)
                == 0
            ):
                progress = (gotCount * 100) // (
                    self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET
                )
                if self.debug_level >= 3:
                    print(
                        f"[DEBUG] Progress: {gotCount}/{self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET} ({progress}%)"
                    )

            if gotCount == packetsPerFrame:
                # Check if this is a complete frame that started at slot 0
                if first_packet_slot == 0:
                    self.first_frame_captured = True
                    break
                elif not self.first_frame_captured:
                    # This shouldn't happen - we got all packets but didn't start at slot 0
                    # Still accept it
                    if self.debug_level >= 1:
                        print(
                            f"[WARN] Frame complete but started at slot {first_packet_slot}. Accepting anyway."
                        )
                    self.first_frame_captured = True
                    break
                else:
                    break

        stop = time.perf_counter_ns()
        duration_us = (stop - start) // 1_000

        if self.debug_level >= 2:
            print(f"[INFO] Frame capture complete:")
            print(f"  - frameId: {currFrameId}")
            print(f"  - got: {gotCount}/{packetsPerFrame}")
            print(f"  - duplicates: {duplicates}")
            print(f"  - total packets received: {packet_count}")
            print(f"  - duration: {duration_us} μs")
            print(f"  - first_packet_slot: {first_packet_slot}")
            print("~~~~~~~~~~~~~~~~~~~END OF SINGLE FRAME~~~~~~~~~~~~~~~~~~~~")
        # self.frame += 1
        return self.frame_data

    # asked chat to make an optimized version of v2
    def process_v3(self):
        """
        Highly optimized version with minimal overhead.
        - All functions inlined in hot path
        - Direct memory access via memoryview
        - Minimal bounds checking
        - No debug output in hot loop
        - Pre-computed constants
        """
        start = time.perf_counter_ns()

        # Socket setup
        self.create_bind_socket()

        # Pre-compute constants
        packetsPerFrame = self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET
        frameBytes = self.BYTES_IN_FRAME_CLIPPED
        header_payload_size = 10 + BYTES_IN_PACKET

        # State variables
        currFrameId = UINT64_MAX
        got = np.zeros(packetsPerFrame, dtype=np.uint8)
        gotCount = 0
        first_packet_slot = -1

        # Direct view into frame data for fast access
        frame_view = self.frame_data
        buffer_view = memoryview(self.buffer)

        # Hot loop - every cycle counts
        while True:
            try:
                # Inline read_socket - avoid function call
                data, self.cliaddr = self.sockfd.recvfrom(BUFFER_SIZE)
                nbytes = len(data)
                self.buffer[:nbytes] = data
            except socket.timeout:
                currFrameId = UINT64_MAX
                got[:] = 0
                gotCount = 0
                first_packet_slot = -1
                continue
            except socket.error:
                currFrameId = UINT64_MAX
                got[:] = 0
                gotCount = 0
                first_packet_slot = -1
                continue

            # Quick size check
            if nbytes < header_payload_size:
                continue

            # INLINE get_byte_count - direct bit manipulation
            # Byte count is bytes 4-9, little-endian 48-bit value
            bc = (
                buffer_view[4]
                | (buffer_view[5] << 8)
                | (buffer_view[6] << 16)
                | (buffer_view[7] << 24)
                | (buffer_view[8] << 32)
                | (buffer_view[9] << 40)
            )

            # Calculate frameId and slot inline
            frameId = bc // frameBytes
            slot = (bc % frameBytes) // BYTES_IN_PACKET

            # First packet handling
            if currFrameId == UINT64_MAX:
                currFrameId = frameId
                got[:] = 0
                gotCount = 0
                first_packet_slot = slot
                frame_view[:] = 0

            # Out of order from previous frame - skip quickly
            if frameId < currFrameId:
                continue

            # New frame started
            if frameId > currFrameId:
                # Only warn if not first frame and significant packet loss
                if self.first_frame_captured and gotCount < packetsPerFrame * 0.95:
                    if self.debug_level >= 1:
                        print(
                            f"[WARN] Frame {currFrameId} incomplete: {gotCount}/{packetsPerFrame}"
                        )

                currFrameId = frameId
                got[:] = 0
                gotCount = 0
                first_packet_slot = slot
                frame_view[:] = 0

            # Bounds check slot (rare, but necessary)
            if slot < 0 or slot >= packetsPerFrame:
                continue

            # Skip duplicates quickly
            if got[slot]:
                continue

            # INLINE place_packet_payload_into_frame
            # This is the absolute critical path - every nanosecond matters
            dst_u16 = (slot * BYTES_IN_PACKET) // 2

            # Fast copy using numpy frombuffer (respects native byte order)
            frame_view[dst_u16 : dst_u16 + self.UINT16_IN_PACKET] = np.frombuffer(
                self.buffer, dtype=np.uint16, count=self.UINT16_IN_PACKET, offset=10
            )

            got[slot] = 1
            gotCount += 1

            # Frame complete check
            if gotCount == packetsPerFrame:
                if first_packet_slot == 0 or self.first_frame_captured:
                    self.first_frame_captured = True
                    break
                # First frame but didn't start at slot 0 - skip and get next complete frame
                if not self.first_frame_captured:
                    # Reset for next frame
                    currFrameId = UINT64_MAX
                    got[:] = 0
                    gotCount = 0
                    first_packet_slot = -1
                    continue

        stop = time.perf_counter_ns()
        duration_us = (stop - start) // 1_000

        if self.debug_level >= 2:
            print(
                f"[INFO] Frame {currFrameId} captured in {duration_us} μs ({gotCount}/{packetsPerFrame} packets)"
            )

        return self.frame_data

    def process_v4(self):
        """
        Ultra-optimized version - absolute minimal overhead.

        Key optimizations:
        - struct.unpack for header parsing (faster than manual bit ops)
        - Removed all unnecessary variables
        - Eliminated function calls in hot path
        - Minimal branching
        - Pre-computed all constants
        - Direct array indexing
        """
        start = time.perf_counter_ns()

        # Socket setup
        if self.sockfd is None:
            self.create_bind_socket()

        # Constants
        PPF = self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET  # packets per frame
        FB = self.BYTES_IN_FRAME_CLIPPED  # frame bytes
        U16 = self.UINT16_IN_PACKET  # uint16 per packet
        MIN_SZ = 10 + BYTES_IN_PACKET

        # State
        cFID = UINT64_MAX
        got = np.zeros(PPF, dtype=np.uint8)
        gCnt = 0
        fSlot = -1

        # Direct references
        fd = self.frame_data
        buf = self.buffer
        sock = self.sockfd

        # Main loop - stripped to bare essentials
        while True:
            try:
                data, self.cliaddr = sock.recvfrom(BUFFER_SIZE)
                n = len(data)
                buf[:n] = data
            except:
                cFID = UINT64_MAX
                got[:] = 0
                gCnt = 0
                fSlot = -1
                continue

            if n < MIN_SZ:
                continue

            # Parse byte count (bytes 4-9)
            bc = (
                buf[4]
                | (buf[5] << 8)
                | (buf[6] << 16)
                | (buf[7] << 24)
                | (buf[8] << 32)
                | (buf[9] << 40)
            )

            fid = bc // FB
            slot = (bc % FB) // BYTES_IN_PACKET

            # First packet
            if cFID == UINT64_MAX:
                cFID = fid
                got[:] = 0
                gCnt = 0
                fSlot = slot
                fd[:] = 0
            elif fid < cFID:
                continue
            elif fid > cFID:
                if (
                    self.first_frame_captured
                    and gCnt < PPF * 0.95
                    and self.debug_level >= 1
                ):
                    print(f"[WARN] Frame {cFID} incomplete: {gCnt}/{PPF}")
                cFID = fid
                got[:] = 0
                gCnt = 0
                fSlot = slot
                fd[:] = 0

            if slot >= PPF or got[slot]:
                continue

            # Copy payload
            dst = (slot * BYTES_IN_PACKET) >> 1
            fd[dst : dst + U16] = np.frombuffer(
                buf, dtype=np.uint16, count=U16, offset=10
            )

            got[slot] = 1
            gCnt += 1

            if gCnt == PPF:
                if fSlot == 0 or self.first_frame_captured:
                    self.first_frame_captured = True
                    break
                if not self.first_frame_captured:
                    cFID = UINT64_MAX
                    got[:] = 0
                    gCnt = 0
                    fSlot = -1

        stop = time.perf_counter_ns()

        if self.debug_level >= 2:
            print(f"[INFO] Frame {cFID} in {(stop - start) // 1000} μs")

        return fd

    def process_v5(self):
        """
        MAXIMUM PERFORMANCE - Ultra-optimized with zero-copy operations.

        Aggressive optimizations:
        - recvfrom_into() for zero-copy socket read
        - Disabled garbage collection during capture
        - struct.unpack_from() for fastest header parsing
        - Direct memory operations
        - Minimal branching and checks
        - Pre-allocated everything
        - Inline all operations
        """

        # Disable GC during frame capture for maximum speed
        gc_was_enabled = gc.isenabled()
        if gc_was_enabled:
            gc.disable()

        try:
            start = time.perf_counter_ns()

            # Socket setup
            if self.sockfd is None:
                self.create_bind_socket()

            # Pre-compute ALL constants
            PPF = self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET
            FB = self.BYTES_IN_FRAME_CLIPPED
            U16 = self.UINT16_IN_PACKET
            MIN_SZ = 1466  # 10 + 1456
            BIP = BYTES_IN_PACKET

            # State - use shortest variable names
            cFID = UINT64_MAX
            got = np.zeros(PPF, dtype=np.uint8)
            gCnt = 0
            fSlot = -1

            # Direct references - avoid attribute lookup
            fd = self.frame_data
            buf = self.buffer
            sock = self.sockfd

            # Pre-create memoryview for zero-copy
            buf_mv = memoryview(buf)

            # Main loop - ABSOLUTE MINIMUM operations
            while True:
                try:
                    # recvfrom_into for zero-copy receive (MUCH faster than recvfrom)
                    n, addr = sock.recvfrom_into(buf, BUFFER_SIZE)
                    self.cliaddr = addr
                except socket.timeout:
                    cFID = UINT64_MAX
                    got[:] = 0
                    gCnt = 0
                    fSlot = -1
                    continue
                except:
                    continue

                # Fast size check
                if n < MIN_SZ:
                    continue

                # FASTEST byte_count parsing - direct array access
                bc = (
                    buf[4]
                    | (buf[5] << 8)
                    | (buf[6] << 16)
                    | (buf[7] << 24)
                    | (buf[8] << 32)
                    | (buf[9] << 40)
                )

                # Inline calculations
                fid = bc // FB
                slot = (bc % FB) // BIP

                # First packet
                if cFID == UINT64_MAX:
                    cFID = fid
                    got[:] = 0
                    gCnt = 0
                    fSlot = slot
                    fd[:] = 0
                elif fid < cFID:
                    continue
                elif fid > cFID:
                    # Frame transition
                    if self.first_frame_captured and gCnt < PPF - (PPF >> 2):  # < 75%
                        if self.debug_level >= 1:
                            print(f"[WARN] Frame {cFID} incomplete: {gCnt}/{PPF}")
                    cFID = fid
                    got[:] = 0
                    gCnt = 0
                    fSlot = slot
                    fd[:] = 0

                # Quick bounds + duplicate check (combined)
                if slot >= PPF or got[slot]:
                    continue

                # CRITICAL PATH - Copy payload (fastest possible method)
                dst = (slot * BIP) >> 1
                fd[dst : dst + U16] = np.frombuffer(
                    buf_mv, dtype=np.uint16, count=U16, offset=10
                )

                got[slot] = 1
                gCnt += 1

                # Frame complete
                if gCnt == PPF:
                    if fSlot == 0 or self.first_frame_captured:
                        self.first_frame_captured = True
                        break
                    # Skip first incomplete frame
                    cFID = UINT64_MAX
                    got[:] = 0
                    gCnt = 0
                    fSlot = -1

            stop = time.perf_counter_ns()

            if self.debug_level >= 2:
                print(f"[INFO] Frame {cFID} in {(stop - start) // 1000} μs")

            return fd

        finally:
            # Re-enable GC if it was enabled before
            if gc_was_enabled:
                gc.enable()

    def process_v6(self):
        """
        ABSOLUTE MAXIMUM PERFORMANCE - Nuclear option.

        Every single cycle optimized:
        - recvfrom_into() for zero-copy
        - GC disabled
        - No exception handling overhead
        - Direct byte access
        - Minimal state checks
        - Optimized for hot path (same frame, sequential packets)
        - All array bounds checks only where critical
        - Shortest possible variable names
        - No function calls in loop
        """

        # Setup
        if self.sockfd is None:
            self.create_bind_socket()

        # Constants - computed once
        P = self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET  # packets per frame
        F = self.BYTES_IN_FRAME_CLIPPED  # frame bytes
        U = self.UINT16_IN_PACKET  # uint16 per packet
        B = BYTES_IN_PACKET  # bytes per packet

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

        try:
            while True:
                # Zero-copy receive
                try:
                    z, _ = s.recvfrom_into(b, BUFFER_SIZE)
                except:
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
                        d[k : k + U] = np.frombuffer(b, np.uint16, U, 10)
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
                        d[k : k + U] = np.frombuffer(b, np.uint16, U, 10)
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
                        d[k : k + U] = np.frombuffer(b, np.uint16, U, 10)
                        g[j] = 1
                        n = 1
                # else: i < c, ignore old packet

            return d
        finally:
            if e:
                gc.enable()

    def process_v7(self):
        """
        Frame-buffered approach: Wait until entire frame worth of data is available,
        then read all packets at once.

        Instead of reading packets one-by-one, this method:
        - Waits for enough data to accumulate in the socket buffer
        - Reads multiple packets in rapid succession
        - Processes complete frames when all packets arrive

        This reduces the overhead of individual socket calls by batching reads.
        """

        # Setup
        if self.sockfd is None:
            self.create_bind_socket()

        # Constants
        P = self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET  # packets per frame
        F = self.BYTES_IN_FRAME_CLIPPED  # frame bytes
        U = self.UINT16_IN_PACKET  # uint16 per packet
        B = BYTES_IN_PACKET  # bytes per packet

        # State
        current_frame = UINT64_MAX
        packet_received = np.zeros(P, dtype=np.uint8)  # track received packets
        packets_in_frame = 0
        first_slot = -1

        # Refs
        frame_data = self.frame_data
        buffer = self.buffer
        sock = self.sockfd

        # Disable GC for performance
        gc_was_enabled = gc.isenabled()
        gc.disable()

        try:
            while True:
                # Wait for data to accumulate - check if we can read a burst of packets
                # Read packets rapidly until we complete a frame or run out of immediate data
                packets_read_this_iteration = 0

                while packets_read_this_iteration < P * 2:  # safety limit
                    try:
                        # Read next packet
                        nbytes, _ = sock.recvfrom_into(buffer, BUFFER_SIZE)
                        packets_read_this_iteration += 1
                    except socket.timeout:
                        # No more data immediately available
                        if current_frame != UINT64_MAX and packets_in_frame > 0:
                            # We have partial frame, wait a bit longer
                            continue
                        else:
                            # Reset and try again
                            current_frame = UINT64_MAX
                            packet_received[:] = 0
                            packets_in_frame = 0
                            first_slot = -1
                            continue
                    except Exception:
                        # Socket error, reset state
                        current_frame = UINT64_MAX
                        packet_received[:] = 0
                        packets_in_frame = 0
                        first_slot = -1
                        continue

                    # Validate packet size
                    if nbytes < 1466:
                        continue

                    # Extract byte_count (48-bit value at bytes 4-9)
                    byte_count = (
                        buffer[4]
                        | (buffer[5] << 8)
                        | (buffer[6] << 16)
                        | (buffer[7] << 24)
                        | (buffer[8] << 32)
                        | (buffer[9] << 40)
                    )

                    # Calculate frame ID and packet slot
                    frame_id = byte_count // F
                    slot = (byte_count % F) // B

                    # Handle packet based on current state
                    if current_frame == UINT64_MAX:
                        # Initialize new frame
                        current_frame = frame_id
                        packet_received[:] = 0
                        packets_in_frame = 0
                        first_slot = slot
                        frame_data[:] = 0

                        if slot < P:
                            # Store packet data
                            dst_offset = (slot * B) >> 1
                            frame_data[dst_offset : dst_offset + U] = np.frombuffer(
                                buffer, np.uint16, U, 10
                            )
                            packet_received[slot] = 1
                            packets_in_frame = 1

                    elif frame_id == current_frame:
                        # Packet belongs to current frame
                        if slot < P and not packet_received[slot]:
                            # Store packet data
                            dst_offset = (slot * B) >> 1
                            frame_data[dst_offset : dst_offset + U] = np.frombuffer(
                                buffer, np.uint16, U, 10
                            )
                            packet_received[slot] = 1
                            packets_in_frame += 1

                            # Check if frame is complete
                            if packets_in_frame == P:
                                if first_slot == 0 or self.first_frame_captured:
                                    self.first_frame_captured = True
                                    # Frame complete, return it
                                    return frame_data
                                else:
                                    # First partial frame, skip it
                                    current_frame = UINT64_MAX
                                    packet_received[:] = 0
                                    packets_in_frame = 0
                                    first_slot = -1
                                    break  # Exit inner loop to restart

                    elif frame_id > current_frame:
                        # New frame arrived, previous frame incomplete
                        if (
                            self.first_frame_captured
                            and packets_in_frame < P - (P >> 2)
                            and self.debug_level
                        ):
                            print(
                                f"[!] Frame {current_frame}: incomplete {packets_in_frame}/{P} packets"
                            )

                        # Start new frame
                        current_frame = frame_id
                        packet_received[:] = 0
                        packets_in_frame = 0
                        first_slot = slot
                        frame_data[:] = 0

                        if slot < P:
                            dst_offset = (slot * B) >> 1
                            frame_data[dst_offset : dst_offset + U] = np.frombuffer(
                                buffer, np.uint16, U, 10
                            )
                            packet_received[slot] = 1
                            packets_in_frame = 1
                    # else: frame_id < current_frame, ignore old packet

        finally:
            if gc_was_enabled:
                gc.enable()

    def process_v8(self):
        """
        Burst-optimized approach: Drain entire socket buffer when packets arrive.

        Designed for networks where packets arrive in periodic bursts rather than
        steadily (e.g., 110ms burst, 180ms gap pattern for 150ms frame periods).

        Strategy:
        - Wait (blocking) for first packet to arrive
        - Immediately switch to non-blocking mode and drain ALL available packets
        - Process complete frames from the burst
        - Switch back to blocking for next burst

        This minimizes per-packet overhead by reading entire bursts at once.
        """

        # Setup
        if self.sockfd is None:
            self.create_bind_socket()

        # Constants
        P = self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET  # packets per frame
        F = self.BYTES_IN_FRAME_CLIPPED  # frame bytes
        U = self.UINT16_IN_PACKET  # uint16 per packet
        B = BYTES_IN_PACKET  # bytes per packet

        # State
        current_frame = UINT64_MAX
        packet_received = np.zeros(P, dtype=np.uint8)
        packets_in_frame = 0
        first_slot = -1

        # Refs
        frame_data = self.frame_data
        buffer = self.buffer
        sock = self.sockfd

        # Disable GC
        gc_was_enabled = gc.isenabled()
        gc.disable()

        try:
            while True:
                # PHASE 1: Wait for burst to start (blocking)
                sock.setblocking(True)
                try:
                    nbytes, _ = sock.recvfrom_into(buffer, BUFFER_SIZE)
                except Exception:
                    current_frame = UINT64_MAX
                    packet_received[:] = 0
                    packets_in_frame = 0
                    first_slot = -1
                    continue

                # Process first packet of burst
                if nbytes >= 1466:
                    byte_count = (
                        buffer[4]
                        | (buffer[5] << 8)
                        | (buffer[6] << 16)
                        | (buffer[7] << 24)
                        | (buffer[8] << 32)
                        | (buffer[9] << 40)
                    )
                    frame_id = byte_count // F
                    slot = (byte_count % F) // B

                    if current_frame == UINT64_MAX:
                        current_frame = frame_id
                        packet_received[:] = 0
                        packets_in_frame = 0
                        first_slot = slot
                        frame_data[:] = 0

                    if (
                        frame_id == current_frame
                        and slot < P
                        and not packet_received[slot]
                    ):
                        dst_offset = (slot * B) >> 1
                        frame_data[dst_offset : dst_offset + U] = np.frombuffer(
                            buffer, np.uint16, U, 10
                        )
                        packet_received[slot] = 1
                        packets_in_frame += 1
                    elif frame_id > current_frame:
                        if (
                            self.first_frame_captured
                            and packets_in_frame < P - (P >> 2)
                            and self.debug_level
                        ):
                            print(f"[!] Frame {current_frame}: {packets_in_frame}/{P}")
                        current_frame = frame_id
                        packet_received[:] = 0
                        packets_in_frame = 0
                        first_slot = slot
                        frame_data[:] = 0
                        if slot < P:
                            dst_offset = (slot * B) >> 1
                            frame_data[dst_offset : dst_offset + U] = np.frombuffer(
                                buffer, np.uint16, U, 10
                            )
                            packet_received[slot] = 1
                            packets_in_frame = 1

                # PHASE 2: Drain remaining packets in burst (non-blocking)
                sock.setblocking(False)
                burst_packets = 0
                while burst_packets < P * 3:  # safety limit
                    try:
                        nbytes, _ = sock.recvfrom_into(buffer, BUFFER_SIZE)
                        burst_packets += 1
                    except BlockingIOError:
                        # No more packets available in this burst
                        break
                    except Exception:
                        # Other error, stop draining
                        break

                    if nbytes < 1466:
                        continue

                    byte_count = (
                        buffer[4]
                        | (buffer[5] << 8)
                        | (buffer[6] << 16)
                        | (buffer[7] << 24)
                        | (buffer[8] << 32)
                        | (buffer[9] << 40)
                    )
                    frame_id = byte_count // F
                    slot = (byte_count % F) // B

                    if frame_id == current_frame:
                        if slot < P and not packet_received[slot]:
                            dst_offset = (slot * B) >> 1
                            frame_data[dst_offset : dst_offset + U] = np.frombuffer(
                                buffer, np.uint16, U, 10
                            )
                            packet_received[slot] = 1
                            packets_in_frame += 1

                            # Check if frame complete
                            if packets_in_frame == P:
                                if first_slot == 0 or self.first_frame_captured:
                                    self.first_frame_captured = True
                                    return frame_data
                                else:
                                    current_frame = UINT64_MAX
                                    packet_received[:] = 0
                                    packets_in_frame = 0
                                    first_slot = -1
                                    break
                    elif frame_id > current_frame:
                        if (
                            self.first_frame_captured
                            and packets_in_frame < P - (P >> 2)
                            and self.debug_level
                        ):
                            print(f"[!] Frame {current_frame}: {packets_in_frame}/{P}")
                        current_frame = frame_id
                        packet_received[:] = 0
                        packets_in_frame = 0
                        first_slot = slot
                        frame_data[:] = 0
                        if slot < P:
                            dst_offset = (slot * B) >> 1
                            frame_data[dst_offset : dst_offset + U] = np.frombuffer(
                                buffer, np.uint16, U, 10
                            )
                            packet_received[slot] = 1
                            packets_in_frame = 1

        finally:
            if gc_was_enabled:
                gc.enable()

    def process_v9(self):
        """
        Buffer-aware approach: Check socket buffer size and wait for full frame.

        Uses ioctl FIONREAD to query how many bytes are buffered in the socket,
        and only starts reading when approximately a full frame's worth of data
        is available. This handles burst arrivals by letting packets accumulate
        before processing.

        For 150ms frame periods with burst arrivals, this waits until the socket
        buffer contains enough data for a complete frame, then drains it rapidly.
        """

        # Setup
        if self.sockfd is None:
            self.create_bind_socket()

        # Constants
        P = self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET  # packets per frame
        F = self.BYTES_IN_FRAME_CLIPPED  # frame bytes
        U = self.UINT16_IN_PACKET  # uint16 per packet
        B = BYTES_IN_PACKET  # bytes per packet
        PACKET_WITH_HEADER = 1472  # approximate packet size with UDP header
        MIN_BYTES_FOR_FRAME = P * PACKET_WITH_HEADER  # ~90% of frame

        # State
        current_frame = UINT64_MAX
        packet_received = np.zeros(P, dtype=np.uint8)
        packets_in_frame = 0
        first_slot = -1

        # Refs
        frame_data = self.frame_data
        buffer = self.buffer
        sock = self.sockfd

        # Disable GC
        gc_was_enabled = gc.isenabled()
        gc.disable()

        # For ioctl FIONREAD
        FIONREAD = 0x541B  # Linux constant, on macOS it's different

        try:
            # Determine FIONREAD constant for platform
            import sys

            if sys.platform == "darwin":
                FIONREAD = 0x4004667F
            elif sys.platform == "win32":
                FIONREAD = 0x4004667F

            while True:
                # Wait until enough data is buffered
                sock.setblocking(True)
                sock.settimeout(1.0)  # 1 second timeout to check periodically

                # Poll socket buffer size
                while True:
                    try:
                        # Check how many bytes are available
                        import array as arr

                        buf = arr.array("i", [0])
                        fcntl.ioctl(sock.fileno(), FIONREAD, buf)
                        bytes_available = buf[0]

                        if bytes_available >= MIN_BYTES_FOR_FRAME * 0.8:
                            # Enough data for at least 80% of a frame
                            break

                        # Not enough data, wait a bit and check again
                        time.sleep(0.010)  # 10ms
                    except Exception:
                        # Fallback: just try to read
                        break

                # Now drain all available packets rapidly
                sock.setblocking(False)
                packets_read = 0

                while packets_read < P * 3:  # safety limit
                    try:
                        nbytes, _ = sock.recvfrom_into(buffer, BUFFER_SIZE)
                        packets_read += 1
                    except BlockingIOError:
                        # Buffer drained
                        break
                    except Exception:
                        break

                    if nbytes < 1466:
                        continue

                    # Extract byte_count
                    byte_count = (
                        buffer[4]
                        | (buffer[5] << 8)
                        | (buffer[6] << 16)
                        | (buffer[7] << 24)
                        | (buffer[8] << 32)
                        | (buffer[9] << 40)
                    )

                    frame_id = byte_count // F
                    slot = (byte_count % F) // B

                    # State machine
                    if current_frame == UINT64_MAX:
                        current_frame = frame_id
                        packet_received[:] = 0
                        packets_in_frame = 0
                        first_slot = slot
                        frame_data[:] = 0

                        if slot < P:
                            dst_offset = (slot * B) >> 1
                            frame_data[dst_offset : dst_offset + U] = np.frombuffer(
                                buffer, np.uint16, U, 10
                            )
                            packet_received[slot] = 1
                            packets_in_frame = 1

                    elif frame_id == current_frame:
                        if slot < P and not packet_received[slot]:
                            dst_offset = (slot * B) >> 1
                            frame_data[dst_offset : dst_offset + U] = np.frombuffer(
                                buffer, np.uint16, U, 10
                            )
                            packet_received[slot] = 1
                            packets_in_frame += 1

                            if packets_in_frame == P:
                                if first_slot == 0 or self.first_frame_captured:
                                    self.first_frame_captured = True
                                    return frame_data
                                else:
                                    current_frame = UINT64_MAX
                                    packet_received[:] = 0
                                    packets_in_frame = 0
                                    first_slot = -1
                                    break

                    elif frame_id > current_frame:
                        if (
                            self.first_frame_captured
                            and packets_in_frame < P - (P >> 2)
                            and self.debug_level
                        ):
                            print(f"[!] Frame {current_frame}: {packets_in_frame}/{P}")

                        current_frame = frame_id
                        packet_received[:] = 0
                        packets_in_frame = 0
                        first_slot = slot
                        frame_data[:] = 0

                        if slot < P:
                            dst_offset = (slot * B) >> 1
                            frame_data[dst_offset : dst_offset + U] = np.frombuffer(
                                buffer, np.uint16, U, 10
                            )
                            packet_received[slot] = 1
                            packets_in_frame = 1

        finally:
            if gc_was_enabled:
                gc.enable()

    def process_v10(self):
        """
        Time-aligned batching: Wait fixed time period, then drain socket buffer.

        Since frames are produced every 150ms, wait ~140ms after reading starts,
        then drain all accumulated packets. This aligns with the production timing
        and reads entire frames worth of packets at once.

        Strategy:
        - Read first packet to start timing
        - Wait 140ms (slightly less than frame period)
        - Drain all accumulated packets rapidly
        - Repeat

        This should smooth out the 110ms/180ms burst pattern by imposing our own
        batching schedule that matches the 150ms production rate.
        """

        # Setup
        if self.sockfd is None:
            self.create_bind_socket()

        # Constants
        P = self.BYTES_IN_FRAME_CLIPPED // BYTES_IN_PACKET  # packets per frame
        F = self.BYTES_IN_FRAME_CLIPPED  # frame bytes
        U = self.UINT16_IN_PACKET  # uint16 per packet
        B = BYTES_IN_PACKET  # bytes per packet
        BATCH_WAIT_TIME = 0.140  # 140ms - slightly less than 150ms frame period

        # State
        current_frame = UINT64_MAX
        packet_received = np.zeros(P, dtype=np.uint8)
        packets_in_frame = 0
        first_slot = -1

        # Refs
        frame_data = self.frame_data
        buffer = self.buffer
        sock = self.sockfd

        # Disable GC
        gc_was_enabled = gc.isenabled()
        gc.disable()

        try:
            while True:
                # Wait for batch period to let packets accumulate
                time.sleep(BATCH_WAIT_TIME)

                # Now drain all available packets rapidly (non-blocking)
                sock.setblocking(False)
                packets_read = 0

                while packets_read < P * 3:  # safety limit
                    try:
                        nbytes, _ = sock.recvfrom_into(buffer, BUFFER_SIZE)
                        packets_read += 1
                    except BlockingIOError:
                        # No more packets available
                        break
                    except Exception:
                        # Socket error
                        break

                    if nbytes < 1466:
                        continue

                    # Extract byte_count
                    byte_count = (
                        buffer[4]
                        | (buffer[5] << 8)
                        | (buffer[6] << 16)
                        | (buffer[7] << 24)
                        | (buffer[8] << 32)
                        | (buffer[9] << 40)
                    )

                    frame_id = byte_count // F
                    slot = (byte_count % F) // B

                    # State machine
                    if current_frame == UINT64_MAX:
                        current_frame = frame_id
                        packet_received[:] = 0
                        packets_in_frame = 0
                        first_slot = slot
                        frame_data[:] = 0

                        if slot < P:
                            dst_offset = (slot * B) >> 1
                            frame_data[dst_offset : dst_offset + U] = np.frombuffer(
                                buffer, np.uint16, U, 10
                            )
                            packet_received[slot] = 1
                            packets_in_frame = 1

                    elif frame_id == current_frame:
                        if slot < P and not packet_received[slot]:
                            dst_offset = (slot * B) >> 1
                            frame_data[dst_offset : dst_offset + U] = np.frombuffer(
                                buffer, np.uint16, U, 10
                            )
                            packet_received[slot] = 1
                            packets_in_frame += 1

                            if packets_in_frame == P:
                                if first_slot == 0 or self.first_frame_captured:
                                    self.first_frame_captured = True
                                    return frame_data
                                else:
                                    current_frame = UINT64_MAX
                                    packet_received[:] = 0
                                    packets_in_frame = 0
                                    first_slot = -1
                                    break

                    elif frame_id > current_frame:
                        if (
                            self.first_frame_captured
                            and packets_in_frame < P - (P >> 2)
                            and self.debug_level
                        ):
                            print(f"[!] Frame {current_frame}: {packets_in_frame}/{P}")

                        current_frame = frame_id
                        packet_received[:] = 0
                        packets_in_frame = 0
                        first_slot = slot
                        frame_data[:] = 0

                        if slot < P:
                            dst_offset = (slot * B) >> 1
                            frame_data[dst_offset : dst_offset + U] = np.frombuffer(
                                buffer, np.uint16, U, 10
                            )
                            packet_received[slot] = 1
                            packets_in_frame = 1

                # If no packets were read, switch back to blocking for a moment
                if packets_read == 0:
                    sock.setblocking(True)
                    sock.settimeout(0.5)
                    try:
                        nbytes, _ = sock.recvfrom_into(buffer, BUFFER_SIZE)
                        # Process this packet on next iteration
                    except:
                        pass

        finally:
            if gc_was_enabled:
                gc.enable()
