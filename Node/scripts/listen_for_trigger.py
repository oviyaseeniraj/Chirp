#!/usr/bin/env python3
"""
MQTT listener on Jetson that waits for collection trigger from backend
This runs continuously and starts data collection when triggered
"""

import os
import sys
import json
import subprocess
import asyncio
from datetime import datetime

try:
    from paho.mqtt import client as mqtt_client
except ImportError:
    print("Error: paho-mqtt not installed")
    print("Install: pip3 install paho-mqtt")
    sys.exit(1)

# Configuration
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = "radar/control/trigger"
RADAR_NAME = os.getenv("RADAR_NAME", "UnknownRadar")

# Paths (adjust as needed)
TEST_DIR = os.path.expanduser("~/Documents/Chirp/Node/test/non_thread")
TEST_BINARY = os.path.join(TEST_DIR, "test")
PUBLISHER_SCRIPT = os.path.expanduser("~/Documents/Chirp/Node/src/rpl/mqtt_publisher.py")

def on_connect(client, userdata, flags, rc):
    """Called when connected to MQTT broker"""
    if rc == 0:
        print(f"Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
        print(f"Listening on topic: {MQTT_TOPIC}")
        print(f"Radar: {RADAR_NAME}")
        print("")
        print("Waiting for trigger command...")
        client.subscribe(MQTT_TOPIC)
    else:
        print(f"Failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    """Called when a message is received"""
    try:
        print(f"\n{'='*60}")
        print(f"TRIGGER RECEIVED! {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*60}\n")
        
        # Parse the trigger message
        payload = eval(msg.payload.decode())  # Simple eval for dict string
        frames = payload.get("frames", 100)
        
        print(f"Radar: {RADAR_NAME}")
        print(f"Frames: {frames}")
        print("")
        
        # Step 1: Run data collection
        print(f"Starting data collection...")
        result = subprocess.run(
            [TEST_BINARY, str(frames)],
            cwd=TEST_DIR,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"Data collection complete!")
        else:
            print(f"Data collection failed!")
            print(result.stderr)
            return
        
        # Step 2: Publish to MQTT
        print(f"Publishing frames to MQTT...")
        result = subprocess.run(
            [
                "python3",
                PUBLISHER_SCRIPT,
                "--broker", MQTT_BROKER,
                "--radar", RADAR_NAME,
                "--once"
            ],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"Frames published to MQTT!")
        else:
            print(f"Publishing failed!")
            print(result.stderr)
        
        print("")
        print("Waiting for next trigger...")
        
    except Exception as e:
        print(f"Error processing trigger: {e}")

def main():
    print("="*60)
    print("Jetson MQTT Trigger Listener")
    print("="*60)
    print("")
    
    # Check if test binary exists
    if not os.path.exists(TEST_BINARY):
        print(f"Error: Test binary not found at {TEST_BINARY}")
        sys.exit(1)
    
    # Create MQTT client
    client = mqtt_client.Client(f"jetson_{RADAR_NAME}")
    client.on_connect = on_connect
    client.on_message = on_message
    
    # Connect to broker
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n\nShutting down listener...")
        client.disconnect()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

