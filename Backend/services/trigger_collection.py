#!/usr/bin/env python3
"""
MQTT-based trigger to start data collection on all Jetsons
Usage: python trigger_collection.py --frames 100
"""

import asyncio
import argparse
from aiomqtt import Client

async def trigger_collection(broker: str, port: int, frames: int):
    """Send trigger command to all Jetsons via MQTT"""
    
    print(f"Triggering data collection on all Jetsons")
    print(f"   Broker: {broker}:{port}")
    print(f"   Frames: {frames}")
    print("")
    
    async with Client(hostname=broker, port=port) as client:
        # Publish trigger command
        trigger_msg = {
            "command": "start_collection",
            "frames": frames,
            "timestamp": asyncio.get_event_loop().time()
        }
        
        # Broadcast to all radars
        await client.publish(
            "radar/control/trigger",
            payload=str(trigger_msg).encode(),
            qos=1
        )
        
        print("Trigger sent to all Jetsons!")
        print("")
        print("Monitor calibration:")
        print("   docker logs -f calibration_processor")
        print("")

def main():
    parser = argparse.ArgumentParser(description="Trigger data collection on all Jetsons via MQTT")
    parser.add_argument("--broker", default="localhost", help="MQTT broker address")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--frames", type=int, default=100, help="Number of frames to collect")
    
    args = parser.parse_args()
    
    asyncio.run(trigger_collection(args.broker, args.port, args.frames))

if __name__ == "__main__":
    main()

