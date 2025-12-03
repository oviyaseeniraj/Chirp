#!/usr/bin/env python3
"""
Test publisher for calibration system - simulates multiple radar nodes
Use this to test the system without physical Jetsons
"""

import asyncio
import json
import time
import math
import random
from aiomqtt import Client
import argparse

def generate_synthetic_trajectory(num_frames, initial_pos=(20, 40), velocity=(-0.5, -1.0)):
    """Generate synthetic target trajectory"""
    trajectory = []
    x, y = initial_pos
    vx, vy = velocity
    
    for _ in range(num_frames):
        # Add some noise
        noise_x = random.gauss(0, 0.5)
        noise_y = random.gauss(0, 0.5)
        
        x += vx + noise_x
        y += vy + noise_y
        
        trajectory.append((x, y))
    
    return trajectory

def cartesian_to_polar(x, y, radar_x, radar_y, radar_orientation_deg):
    """Convert Cartesian target position to radar's polar coordinates"""
    # Relative to radar
    dx = x - radar_x
    dy = y - radar_y
    
    # Range
    range_m = math.sqrt(dx**2 + dy**2)
    
    # Angle relative to global frame
    angle_global = math.degrees(math.atan2(dy, dx))
    
    # Angle relative to radar orientation
    angle_relative = angle_global - radar_orientation_deg
    
    # Normalize to [-180, 180]
    while angle_relative > 180:
        angle_relative -= 360
    while angle_relative < -180:
        angle_relative += 360
    
    return angle_relative, range_m

async def publish_radar_frames(client, radar_config, trajectory, delay_ms=100):
    """Publish frames for one radar"""
    radar_name = radar_config['name']
    radar_x = radar_config['x']
    radar_y = radar_config['y']
    radar_orientation = radar_config['orientation']
    
    print(f"\n{radar_name}: Starting data collection ({len(trajectory)} frames)")
    
    for frame_num, (target_x, target_y) in enumerate(trajectory, 1):
        # Convert to radar's polar coordinates
        angle, range_m = cartesian_to_polar(
            target_x, target_y, 
            radar_x, radar_y, 
            radar_orientation
        )
        
        # Create MQTT payload
        payload = {
            "radar_name": radar_name,
            "frame": frame_num,
            "angle": round(angle, 2),
            "range": round(range_m, 2),
            "timestamp_ns": int(time.time() * 1e9)
        }
        
        # Publish to MQTT
        topic = f"radar/{radar_name}/frame"
        await client.publish(topic, json.dumps(payload))
        
        print(f"{radar_name}: Frame {frame_num}/{len(trajectory)} - "
              f"angle={angle:.1f}°, range={range_m:.2f}m")
        
        # Delay between frames (simulate radar frame rate)
        await asyncio.sleep(delay_ms / 1000.0)
    
    print(f"{radar_name}: ✓ Complete")

async def main():
    parser = argparse.ArgumentParser(
        description="Test publisher for calibration system"
    )
    parser.add_argument(
        "--broker", 
        default="localhost",
        help="MQTT broker address"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=1883,
        help="MQTT broker port"
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=100,
        help="Number of frames to generate"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=100,
        help="Delay between frames in milliseconds"
    )
    parser.add_argument(
        "--radars",
        type=int,
        default=2,
        help="Number of radar nodes to simulate (2-4)"
    )
    
    args = parser.parse_args()
    
    # Radar configurations (square formation)
    radar_configs = [
        {"name": "Patrick", "x": 0, "y": 0, "orientation": 45},
        {"name": "Mike", "x": 40, "y": 0, "orientation": 135},
        {"name": "John", "x": 40, "y": 40, "orientation": 225},
        {"name": "Sarah", "x": 0, "y": 40, "orientation": 315},
    ]
    
    # Use only requested number of radars
    radar_configs = radar_configs[:args.radars]
    
    # Generate shared trajectory (target moves through overlapping FOV)
    trajectory = generate_synthetic_trajectory(
        args.frames,
        initial_pos=(20, 40),
        velocity=(-0.3, -0.8)
    )
    
    print("="*60)
    print("Test Publisher for Calibration System")
    print("="*60)
    print(f"MQTT Broker: {args.broker}:{args.port}")
    print(f"Radars: {args.radars} ({', '.join(r['name'] for r in radar_configs)})")
    print(f"Frames: {args.frames}")
    print(f"Frame delay: {args.delay}ms")
    print("="*60)
    
    # Connect to MQTT
    async with Client(args.broker, args.port) as client:
        print("\n✓ Connected to MQTT broker")
        
        # Publish frames from all radars simultaneously
        tasks = [
            publish_radar_frames(client, config, trajectory, args.delay)
            for config in radar_configs
        ]
        
        await asyncio.gather(*tasks)
        
        print("\n" + "="*60)
        print("✓ All radars finished publishing")
        print(f"✓ Total frames: {args.frames * args.radars}")
        print("="*60)
        print("\nCheck calibration processor logs:")
        print("  docker logs -f calibration_processor")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nStopped by user")




