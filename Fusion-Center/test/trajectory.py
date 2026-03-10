#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import sys
import time
import pickle
from aiohttp import web
import socketio

# Configuration
PORT = 5001
MAX_FRAMES_PER_NODE = 100
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "temp")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Async SocketIO Server
sio = socketio.AsyncServer(
    async_mode='aiohttp', 
    cors_allowed_origins='*',
    max_http_buffer_size=10000000 
)
app = web.Application()
sio.attach(app)

class DataCollector:
    def __init__(self, max_frames=MAX_FRAMES_PER_NODE):
        self.node_data = {}  # node_id -> list of frames
        self.max_frames = max_frames
        self.start_time = time.time()
        self.total_frames_collected = 0

    def add_frame(self, node_id, frame):
        if node_id not in self.node_data:
            self.node_data[node_id] = []
            logger.info(f"Started collecting from Node: {node_id}")

        if len(self.node_data[node_id]) < self.max_frames:
            self.node_data[node_id].append(frame)
            self.total_frames_collected += 1
            
            if len(self.node_data[node_id]) % 10 == 0:
                logger.info(f"Node {node_id}: {len(self.node_data[node_id])}/{self.max_frames} frames collected")
            
            return True
        return False

    def is_complete(self, expected_nodes=None):
        if not self.node_data:
            return False
            
        if expected_nodes:
            # Check if all expected nodes have enough frames
            return all(len(self.node_data.get(node, [])) >= self.max_frames for node in expected_nodes)
        else:
            # Just check if at least one node is done (simple mode)
            return any(len(frames) >= self.max_frames for frames in self.node_data.values())

    def save_data(self):
        timestamp = int(time.time())
        filename = f"capture_{timestamp}.pkl"
        filepath = os.path.join(OUTPUT_DIR, filename)
        
        with open(filepath, 'wb') as f:
            pickle.dump(self.node_data, f)
        
        logger.info(f"Saved data for {len(self.node_data)} nodes to {filepath}")
        return filepath

# Global collector instance
collector = DataCollector()

@sio.event
async def connect(sid, environ):
    logger.info(f"Node connected: {sid}")

@sio.event
async def disconnect(sid):
    logger.info(f"Node disconnected: {sid}")

@sio.on("send_frame")
async def handle_frame(sid, data):
    node_id = data.get("node_id", "unknown_node")
    
    # Extract only what's needed for trajectory generation to save memory
    frame_entry = {
        "timestamp": data.get("frame_num", time.time() * 1000),
        "clusters": data.get("clusters", []),
        "cluster_count": data.get("cluster_count", 0)
    }
    
    if collector.add_frame(node_id, frame_entry):
        if collector.is_complete():
            logger.info("Collection target reached. Saving and shutting down...")
            collector.save_data()
            # Brief delay to ensure save completes before we kill the server
            await asyncio.sleep(1)
            # This is a bit brute force for a server but fits the "capture utility" requirement
            os._exit(0)

async def index_handler(request):
    return web.Response(text="Trajectory Collector is Running", content_type='text/plain')

app.router.add_get('/', index_handler)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fusion Center Trajectory Data Collector")
    parser.add_argument("--port", type=int, default=5001, help="Port to listen on")
    parser.add_argument("--frames", type=int, default=100, help="Frames to collect per node")
    parser.add_argument("--nodes", nargs='+', help="Expected node IDs (optional)")
    
    args = parser.parse_args()
    
    PORT = args.port
    collector.max_frames = args.frames
    
    logger.info(f"Starting Collector on port {PORT}, target: {args.frames} frames per node")
    if args.nodes:
        logger.info(f"Waiting for specific nodes: {', '.join(args.nodes)}")
    
    web.run_app(app, host="0.0.0.0", port=PORT, access_log=None)
