import socket
import struct
import time
import os

# Constants matches DataAcquisition.py
BYTES_IN_PACKET = 1456
PORT = 4098
PACKETS_IN_FRAME = 1080

def send_frame(sock, start_packet_num=0, start_byte_count=0, drop_packet=None):
    current_packet_num = start_packet_num
    current_byte_count = start_byte_count
    
    for i in range(PACKETS_IN_FRAME):
        if i == drop_packet:
            print(f"Dropping packet {current_packet_num}")
            current_packet_num += 1
            current_byte_count += BYTES_IN_PACKET
            continue
            
        # Header: 4 bytes packet number, 6 bytes byte count
        header = struct.pack('<I', current_packet_num)
        header += struct.pack('<I', current_byte_count & 0xFFFFFFFF)
        header += struct.pack('<H', (current_byte_count >> 32) & 0xFFFF)
        
        # Payload: 1456 bytes of dummy data
        payload = os.urandom(BYTES_IN_PACKET)
        
        sock.sendto(header + payload, ('127.0.0.1', PORT))
        
        current_packet_num += 1
        current_byte_count += BYTES_IN_PACKET

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print("Mock DCA1000EVM started. Sending frames...")
    
    try:
        frame_count = 0
        while frame_count < 2:
            print(f"Sending frame {frame_count}...")
            # Simulate a packet drop in the second frame
            drop = 10 if frame_count == 1 else None
            send_frame(sock, start_packet_num=frame_count*PACKETS_IN_FRAME*2, start_byte_count=frame_count*PACKETS_IN_FRAME*BYTES_IN_PACKET*2, drop_packet=drop)
            frame_count += 1
            time.sleep(1)
    finally:
        sock.close()

if __name__ == "__main__":
    main()
