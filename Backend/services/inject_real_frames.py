#!/usr/bin/env python3
"""
Inject real frame data from JSON files into the calibration system via MQTT.
Reads frame files from a directory and publishes them to the MQTT broker.
"""

import asyncio
import json
import os
import re
import time
import argparse
from pathlib import Path

try:
    from aiomqtt import Client
except ImportError:
    print("Installing aiomqtt...")
    os.system("pip install aiomqtt")
    from aiomqtt import Client


async def inject_frames(broker: str, frame_dir: str, delay_ms: int = 50):
    """
    Read JSON frame files and publish them to MQTT.
    
    Args:
        broker: MQTT broker hostname
        frame_dir: Directory containing frame JSON files
        delay_ms: Delay between frames in milliseconds
    """
    frame_path = Path(frame_dir)
    
    # Find all JSON files
    json_files = list(frame_path.glob("*.json"))
    
    if not json_files:
        print(f"No JSON files found in {frame_dir}")
        return
    
    # Parse and sort by frame number
    def extract_frame_num(filepath):
        match = re.search(r'Frame(\d+)\.json$', filepath.name)
        return int(match.group(1)) if match else 0
    
    json_files.sort(key=extract_frame_num)
    
    print("=" * 60)
    print("Real Frame Injector")
    print("=" * 60)
    print(f"MQTT Broker: {broker}:1883")
    print(f"Frame Directory: {frame_dir}")
    print(f"Total Frames: {len(json_files)}")
    print(f"Frame Delay: {delay_ms}ms")
    print("=" * 60)
    
    async with Client(broker, 1883) as client:
        print("\n✓ Connected to MQTT broker\n")
        
        frames_sent = 0
        start_time = time.time()
        
        for json_file in json_files:
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                
                # Extract fields from real frame format
                # {"Node":"Patrick","Frame Number":1,"Elapsed Time (ms)":490,"Angle":-64.0,"Range":1.1953125}
                radar_name = data.get("Node", "Unknown")
                frame_number = data.get("Frame Number", 0)
                angle = data.get("Angle", 0.0)
                range_m = data.get("Range", 0.0)
                elapsed_ms = data.get("Elapsed Time (ms)", 0)
                
                # Create payload in expected format
                payload = {
                    "frame": frame_number,
                    "angle": angle,
                    "range": range_m,
                    "timestamp_ns": int(elapsed_ms * 1_000_000)  # Convert ms to ns
                }
                
                # Publish to MQTT
                topic = f"radar/{radar_name}/frame"
                await client.publish(topic, json.dumps(payload))
                
                frames_sent += 1
                
                # Progress output
                if frames_sent % 50 == 0 or frames_sent == len(json_files):
                    elapsed = time.time() - start_time
                    print(f"  [{frames_sent}/{len(json_files)}] {radar_name} Frame #{frame_number} "
                          f"- angle={angle:.1f}°, range={range_m:.2f}m ({elapsed:.1f}s)")
                
                # Delay between frames
                await asyncio.sleep(delay_ms / 1000.0)
                
            except Exception as e:
                print(f"Error processing {json_file}: {e}")
        
        elapsed = time.time() - start_time
        print()
        print("=" * 60)
        print(f"✓ Injection complete!")
        print(f"✓ Frames sent: {frames_sent}")
        print(f"✓ Time elapsed: {elapsed:.1f}s")
        print("=" * 60)
        print("\nWatch calibration with:")
        print("  docker logs -f calibration_processor")


def main():
    parser = argparse.ArgumentParser(description="Inject real frame data into calibration system")
    parser.add_argument("--broker", default="localhost", help="MQTT broker hostname")
    parser.add_argument("--dir", required=True, help="Directory containing frame JSON files")
    parser.add_argument("--delay", type=int, default=50, help="Delay between frames in ms (default: 50)")
    
    args = parser.parse_args()
    
    asyncio.run(inject_frames(args.broker, args.dir, args.delay))


if __name__ == "__main__":
    main()

