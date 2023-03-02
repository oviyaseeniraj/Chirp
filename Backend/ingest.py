import asyncio
import json
import socket
from aiomqtt import Client, MqttError
import asyncpg
import os

# Read MQTT environment variables (support both BROKER/PORT and the
# docker-compose keys MQTT_BROKER/MQTT_PORT). Default broker name is
# `nanomq` to match the service name used in docker-compose.
BROKER = os.getenv("BROKER") or os.getenv("MQTT_BROKER") or "nanomq"
PORT = int(os.getenv("PORT") or os.getenv("MQTT_PORT") or 1883)
INPUT_TOPIC = os.getenv("MQTT_TOPIC", "input/+/data")

# Postgres connection config (allow overriding host via POSTGRES_HOST)
PG_HOST = os.getenv("POSTGRES_HOST", "db")
PG_USER = os.getenv("POSTGRES_USER", "user")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")
PG_DB = os.getenv("POSTGRES_DB", "mqttdata")

async def init_db():
    conn = await asyncpg.connect(
        host=PG_HOST,
        user=PG_USER,
        password=PG_PASSWORD,
        database=PG_DB
    )
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS radarData (
            id SERIAL PRIMARY KEY,
            uuid VARCHAR(32),
            data BYTEA,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    await conn.close()

async def process_message(pool, message):
    payload = json.loads(message.payload.decode())
    topic = str(message.topic)
    topic_parts = topic.split('/')
    uuid = topic_parts[1]
    data = payload["data"].encode('utf-8')
    print("processing message")
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO radarData (uuid, data) VALUES ($1, $2)",
            uuid, data
        )

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

    # Wait until the broker hostname resolves before attempting MQTT
    await wait_for_broker()

    try:
        print(f"Connecting to MQTT broker {BROKER}:{PORT}, subscribing to {INPUT_TOPIC}")
        async with Client(BROKER, PORT) as client:
            await client.subscribe(INPUT_TOPIC)
            async for message in client.messages:
                asyncio.create_task(process_message(pool, message))
    except MqttError as e:
        print(f"MQTT error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
