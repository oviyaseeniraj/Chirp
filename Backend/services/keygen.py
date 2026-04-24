import asyncio
import json
import socket
from aiomqtt import Client, MqttError
import asyncpg
import os
import uuid as uuid

BROKER = os.getenv("BROKER") or os.getenv("MQTT_BROKER") or "nanomq"
PORT = int(os.getenv("PORT") or os.getenv("MQTT_PORT") or 1883)
INPUT_TOPIC = os.getenv("MQTT_TOPIC", "input/key")


PG_HOST = os.getenv("POSTGRES_HOST", "db")
PG_USER = os.getenv("POSTGRES_USER", "user")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")
PG_DB = os.getenv("POSTGRES_DB", "mqttdata")

async def check_key(pool, client, message):
    payload = json.loads(message.payload.decode())
    uuid = payload["uuid"]
    print(uuid)
    name = payload["name"]
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT uuid FROM node_key WHERE name = $1", name
        )
        key = None
        
        #if the name has not been registered 
        print(f"Result from DB: {result}")
        
        if result is None:
            key = await gen_key(conn)
            print(f"Generated new key: {key}")
            await conn.execute(
                "INSERT INTO node_key (name, uuid) VALUES ($1, $2)",
                name, key
            )
            status = 0

        elif result != uuid:
            print(f"UUID mismatch, setting old key")
            key = result
            print(key)
            status = 0
        
        else:
            key = result
            print(f"Match found!")
            status = 1

        
        
        if(key != None):
            await send_response(client, name, key, status)
        else:
            print("you window licker")


async def gen_key(conn):
    while True:
        key = str(uuid.uuid1().hex)

        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM node_key WHERE uuid = $1)", key
        )

        if not exists: 
            return key;


async def send_response(client, name, uuid, status):
    response = {
        "name" : name,
        "uuid" : uuid,
        "status" : status
    }

    topic = "output/" + name

    await client.publish(topic, json.dumps(response))
    print(f"Sent response: {response}")

async def wait_for_db():
    while True:
        try:
            conn = await asyncpg.connect(
                host=PG_HOST,
                user=PG_USER,
                password=PG_PASSWORD,
                database=PG_DB
            )
            await conn.close()
            break
        except Exception:
            print("Database not ready, retrying in 1s...")
            await asyncio.sleep(1)

async def init_db():
    conn = await asyncpg.connect(
        host=PG_HOST,
        user=PG_USER,
        password=PG_PASSWORD,
        database=PG_DB
    )
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS node_key (
            id SERIAL PRIMARY KEY,
            name VARCHAR(32),
            uuid VARCHAR(32),
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    await conn.close()

async def wait_for_broker():
    """Wait until the MQTT broker hostname resolves (simple DNS check).

    This avoids the common docker-compose mistake of passing the wrong
    env var name and then seeing a ``[Errno -2] Name or service not known``
    when attempting to connect.
    """
    while True:
        try:
            # Use getaddrinfo to allow both names and IPs; it's async-friendly
            loop = asyncio.get_event_loop()
            await loop.getaddrinfo(BROKER, PORT)
            break
        except Exception:
            print(f"MQTT broker {BROKER}:{PORT} not resolvable, retrying in 1s...")
            await asyncio.sleep(1)

async def main():
    await wait_for_db()
    await init_db()
    pool = await asyncpg.create_pool(
        host=PG_HOST,
        user=PG_USER,
        password=PG_PASSWORD,
        database=PG_DB
    )
    #need to check if brocker is up
    await wait_for_broker()
    try:
        print(f"Connecting to MQTT broker {BROKER}:{PORT}, subscribing to {INPUT_TOPIC}")
        async with Client(BROKER, PORT) as client:
            await client.subscribe(INPUT_TOPIC)
            async for message in client.messages:
                asyncio.create_task(check_key(pool, client, message))
    except MqttError as e:
        print(f"MQTT error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
