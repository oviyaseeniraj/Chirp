#!/usr/bin/env python3
import socket
import threading
import time
import logging
import os

# Configuration
HOST = '0.0.0.0'
PORT = 1210
SETTLE_TIMEOUT = 3.0  # Seconds to wait after the last request before finalizing consensus
LOG_FILE = os.path.join(os.path.dirname(__file__), 'arbitrator.log')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

class Arbitrator:
    def __init__(self):
        self.clients = {}  # addr_str -> socket
        self.proposed_times = {} # addr_str -> time
        self.lock = threading.Lock()
        self.last_request_time = 0
        self.max_proposed_time = 0
        self.timer_thread = None

    def start(self):
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((HOST, PORT))
        server_sock.listen(10)
        logging.info(f"Master Arbitrator (Resync enabled) started on {HOST}:{PORT}")

        while True:
            client_sock, client_addr = server_sock.accept()
            addr_str = f"{client_addr[0]}:{client_addr[1]}"
            logging.info(f"New connection from {addr_str}")
            
            with self.lock:
                self.clients[addr_str] = client_sock
            
            threading.Thread(target=self.handle_client, args=(client_sock, addr_str)).start()

    def handle_client(self, sock, addr_str):
        try:
            while True:
                data = sock.recv(1024).decode().strip()
                if not data:
                    break

                try:
                    proposed_time = int(data)
                except ValueError:
                    logging.error(f"Invalid data from {addr_str}: {data}")
                    continue

                logging.info(f"Request from {addr_str}: proposed start time {proposed_time}")

                with self.lock:
                    # Update proposed time for this client
                    self.proposed_times[addr_str] = proposed_time
                    
                    # Update max proposed time
                    if proposed_time > self.max_proposed_time:
                        self.max_proposed_time = proposed_time
                        logging.info(f"New consensus baseline: {self.max_proposed_time}")

                    # Restart/Start the settling timer
                    self.last_request_time = time.time()
                    if self.timer_thread is None or not self.timer_thread.is_alive():
                        self.timer_thread = threading.Thread(target=self.consensus_timer)
                        self.timer_thread.start()
                        logging.info("Consensus timer started/restarted")

        except Exception as e:
            logging.error(f"Error handling client {addr_str}: {e}")
        finally:
            with self.lock:
                if addr_str in self.clients:
                    del self.clients[addr_str]
                if addr_str in self.proposed_times:
                    del self.proposed_times[addr_str]
            sock.close()
            logging.info(f"Connection closed for {addr_str}")

    def consensus_timer(self):
        while True:
            time.sleep(0.5)
            with self.lock:
                if time.time() - self.last_request_time >= SETTLE_TIMEOUT:
                    self.finalize_consensus()
                    break

    def finalize_consensus(self):
        # Ensure consensus is in the future relative to now + buffer
        now = int(time.time())
        final_time = max(self.max_proposed_time, now + 2)
        
        logging.info(f"Finalizing consensus for {len(self.clients)} nodes at time {final_time}")
        
        # Broadcast to ALL connected clients
        msg = str(final_time).encode()
        to_remove = []
        for addr_str, sock in self.clients.items():
            try:
                sock.sendall(msg)
                logging.info(f"Sent consensus {final_time} to {addr_str}")
            except Exception as e:
                logging.error(f"Error sending to {addr_str}: {e}")
                to_remove.append(addr_str)
        
        for addr_str in to_remove:
            del self.clients[addr_str]
            if addr_str in self.proposed_times:
                del self.proposed_times[addr_str]

        # Keep state for resync, but reset baseline for next batch if desired.
        # However, keeping max_proposed_time helps ensure monotonic increases.
        logging.info("Consensus broadcast complete.")

if __name__ == "__main__":
    arbitrator = Arbitrator()
    arbitrator.start()
