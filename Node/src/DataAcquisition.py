import socket
import struct
import array
import time

# Constants (from main.h)
FAST_TIME = 512
SLOW_TIME = 64
RX = 4
TX = 3
IQ = 2
IQ_BYTES = 2
BYTES_IN_PACKET = 1456
PORT = 4098

BYTES_IN_FRAME = SLOW_TIME * FAST_TIME * RX * TX * IQ * IQ_BYTES  # 1,572,864
PACKETS_IN_FRAME = BYTES_IN_FRAME // BYTES_IN_PACKET  # 1080
BYTES_IN_FRAME_CLIPPED = PACKETS_IN_FRAME * BYTES_IN_PACKET  # 1,572,480

BUFFER_SIZE = 2048 # Max UDP packet size

def get_packet(sock):
    """Receives a single UDP packet and returns the raw data."""
    data, addr = sock.recvfrom(BUFFER_SIZE)
    return data

def collect_raw_packets(sock, num_packets):
    """Gathers raw UDP packets into a list."""
    packets = []
    while len(packets) < num_packets:
        data = get_packet(sock)
        if data:
            packets.append(data)
    return packets

def parse_packet(data):
    """Unpacks header (packet_num, byte_count) and extract payload."""
    if len(data) < 10:
        return None, None, None
        
    packet_num = struct.unpack('<I', data[:4])[0]
    byte_count_low = struct.unpack('<I', data[4:8])[0]
    byte_count_high = struct.unpack('<H', data[8:10])[0]
    byte_count = (byte_count_high << 32) | byte_count_low
    payload = data[10:10 + BYTES_IN_PACKET]
    
    return packet_num, byte_count, payload

def validate_sequence(packet_num, byte_count, expected_num, expected_bytes):
    """Checks for packet drops and byte losses, logging warnings if detected."""
    updated_num = expected_num
    updated_bytes = expected_bytes
    
    # Initialize if this is the first packet
    if expected_num is None:
        return packet_num, byte_count

    if packet_num != expected_num:
        diff = packet_num - expected_num
        print(f"Warning: Packet drop detected! Expected {expected_num}, got {packet_num} (lost {diff} packets)")
        updated_num = packet_num
        
    if byte_count != expected_bytes:
        print(f"Warning: Byte count mismatch! Expected {expected_bytes}, got {byte_count}")
        updated_bytes = byte_count
        
    return updated_num, updated_bytes

def build_frame(sock):
    """Orchestrates frame building: collect, parse, validate, and assemble."""
    raw_packets = collect_raw_packets(sock, PACKETS_IN_FRAME)
    frame_data = bytearray(BYTES_IN_FRAME_CLIPPED)
    
    expected_num = None
    expected_bytes = None
    
    for i, raw_data in enumerate(raw_packets):
        packet_num, byte_count, payload = parse_packet(raw_data)
        if packet_num is None:
            continue
            
        expected_num, expected_bytes = validate_sequence(packet_num, byte_count, expected_num, expected_bytes)

        # Assemble into frame buffer
        offset = i * BYTES_IN_PACKET
        if offset + len(payload) <= BYTES_IN_FRAME_CLIPPED:
            frame_data[offset : offset + len(payload)] = payload
            
        expected_num += 1
        expected_bytes += BYTES_IN_PACKET

    return array.array('H', frame_data)

def main():
    # Setup socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('', PORT))
    print(f"Listening on port {PORT}...")
    
    try:
        while True:
            start_time = time.time()
            frame = build_frame(sock)
            end_time = time.time()
            print(f"Frame captured. Size: {len(frame)} elements. Time: {(end_time - start_time)*1000:.2f} ms")
            # Process frame...
            
    except KeyboardInterrupt:
        print("Stopping capture.")
    finally:
        sock.close()

if __name__ == "__main__":
    main()
