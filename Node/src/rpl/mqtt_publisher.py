#!/usr/bin/env python3
"""
MQTT Frame Publisher for Jetson Radar Nodes

This script monitors the frame_data directory for new JSON files
and publishes them to the MQTT broker for real-time calibration.

Usage:
    python3 mqtt_publisher.py [--watch-dir DIR] [--broker HOST] [--port PORT]
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
import paho.mqtt.client as mqtt

class RadarFramePublisher:
    def __init__(self, broker_host="169.231.215.235", broker_port=1883, 
                 watch_dir="/home/fusionsense/Documents/Chirp/Node/test/non_thread/frame_data"):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.watch_dir = Path(watch_dir)
        self.client = None
        self.processed_files = set()
        
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"✓ Connected to MQTT broker at {self.broker_host}:{self.broker_port}")
        else:
            print(f"✗ Connection failed with code {rc}")
    
    def on_publish(self, client, userdata, mid):
        pass  # Silent success
    
    def connect(self):
        """Connect to MQTT broker"""
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_publish = self.on_publish
        
        try:
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_start()
            time.sleep(1)  # Wait for connection
            return True
        except Exception as e:
            print(f"✗ Failed to connect to broker: {e}")
            return False
    
    def publish_frame(self, json_file):
        """Publish a single frame to MQTT"""
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
            
            # Extract radar name and frame info
            radar_name = data.get("Node", "Unknown")
            frame_number = data.get("Frame Number", 0)
            angle = data.get("Angle", 0.0)
            range_m = data.get("Range", 0.0)
            
            # Create MQTT payload with nanosecond timestamp
            timestamp_ns = int(time.time() * 1e9)
            payload = {
                "radar_name": radar_name,
                "frame": frame_number,
                "angle": angle,
                "range": range_m,
                "timestamp_ns": timestamp_ns
            }
            
            # Publish to topic: radar/{radar_name}/frame
            topic = f"radar/{radar_name}/frame"
            self.client.publish(topic, json.dumps(payload))
            
            print(f"Published: {radar_name} Frame {frame_number} (angle={angle:.1f}°, range={range_m:.2f}m)")
            
        except Exception as e:
            print(f"✗ Error publishing {json_file}: {e}")
    
    def scan_and_publish(self):
        """Scan directory for new JSON files and publish them"""
        if not self.watch_dir.exists():
            print(f"✗ Directory not found: {self.watch_dir}")
            return
        
        # Find all JSON files
        json_files = sorted(self.watch_dir.glob("*.json"))
        
        new_files = []
        for json_file in json_files:
            file_str = str(json_file)
            if file_str not in self.processed_files:
                new_files.append(json_file)
                self.processed_files.add(file_str)
        
        # Publish new files
        if new_files:
            print(f"\nFound {len(new_files)} new frame(s)")
            for json_file in new_files:
                self.publish_frame(json_file)
        
        return len(new_files)
    
    def watch_and_publish(self, interval=1.0):
        """Continuously watch directory and publish new frames"""
        print(f"Watching directory: {self.watch_dir}")
        print(f"Publishing to broker: {self.broker_host}:{self.broker_port}")
        print(f"Press Ctrl+C to stop\n")
        
        try:
            while True:
                self.scan_and_publish()
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n\nStopping publisher...")
            self.client.loop_stop()
            self.client.disconnect()
            print("Goodbye!")
    
    def publish_all_once(self):
        """Publish all existing frames once (for batch processing)"""
        count = self.scan_and_publish()
        print(f"\n✓ Published {count} frame(s)")
        self.client.loop_stop()
        self.client.disconnect()

def main():
    parser = argparse.ArgumentParser(
        description="Publish radar frame data to MQTT broker"
    )
    parser.add_argument(
        "--watch-dir", 
        default="/home/fusionsense/Documents/Chirp/Node/test/non_thread/frame_data",
        help="Directory containing JSON frame files"
    )
    parser.add_argument(
        "--broker", 
        default="169.231.215.235",
        help="MQTT broker hostname or IP"
    )
    parser.add_argument(
        "--port", 
        type=int,
        default=1883,
        help="MQTT broker port"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Publish existing files once and exit (no watch mode)"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds (watch mode only)"
    )
    
    args = parser.parse_args()
    
    # Create publisher
    publisher = RadarFramePublisher(
        broker_host=args.broker,
        broker_port=args.port,
        watch_dir=args.watch_dir
    )
    
    # Connect to broker
    if not publisher.connect():
        sys.exit(1)
    
    # Run in appropriate mode
    if args.once:
        publisher.publish_all_once()
    else:
        publisher.watch_and_publish(interval=args.interval)

if __name__ == "__main__":
    main()




