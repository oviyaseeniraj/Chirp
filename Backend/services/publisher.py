import asyncio
import json
import random
import time
from aiomqtt import Client, MqttError
import os

# MQTT configuration
BROKER = os.getenv("MQTT_BROKER", "nanomq")
PORT = int(os.getenv("MQTT_PORT", 1883))
TOPIC = os.getenv("MQTT_TOPIC", "input/")
NAME = os.getenv("DEV_NAME", "Stella")
uuid = None
# PUBLISH_INTERVAL = float(os.getenv("PUBLISH_INTERVAL", 2.0))  # seconds

async def wait_for_broker():
    """Wait until the MQTT broker hostname resolves."""
    while True:
        try:
            loop = asyncio.get_event_loop()
            await loop.getaddrinfo(BROKER, PORT)
            print(f"MQTT broker {BROKER}:{PORT} is reachable")
            break
        except Exception:
            print(f"MQTT broker {BROKER}:{PORT} not reachable, retrying in 1s...")
            await asyncio.sleep(1)

async def set_uuid(message):
    global uuid
    payload = json.loads(message.payload.decode())
    status = payload["status"]
    # dont really need name check 
    print(payload["uuid"])
    uuid = payload["uuid"]

async def send_message(client):
    #here we trigger maybe and send?
    global uuid
    print(uuid)
    print("in send_message")
    while True:
        if uuid is not None:
            await asyncio.sleep(1)
            data = {
                "data" : "skjhafdjaksfhk"
            }
            print("wtf")
            await client.publish("input/" + uuid + "/data", json.dumps(data))
        else:
            await asyncio.sleep(1)
            print("erm")


async def main():
    await wait_for_broker()
    try:
        async with Client(BROKER, PORT) as client:
            await client.subscribe("output/" + NAME)
            # i want to check here
            init = {
                "uuid" : "",
                "name" : NAME
                }

            await client.publish("input/key", json.dumps(init), retain = True)
            asyncio.create_task(send_message(client))
            async for message in client.messages:
                asyncio.create_task(set_uuid(message))
    except MqttError as e:
        print(f"MQTT error: {e}")

if __name__ == "__main__":
    print("Starting MQTT Data Publisher...")
    asyncio.run(main())