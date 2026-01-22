import asyncio
import json
import os
import socket

import asyncpg
from aiomqtt import Client, MqttError

# Read MQTT environment variables (support both BROKER/PORT and the
# docker-compose keys MQTT_BROKER/MQTT_PORT). Default broker name is
# `nanomq` to match the service name used in docker-compose.
BROKER = os.getenv("BROKER") or os.getenv("MQTT_BROKER") or "nanomq"
PORT = int(os.getenv("PORT") or os.getenv("MQTT_PORT") or 1883)
INPUT_TOPIC = os.getenv("MQTT_TOPIC", "input/+/data")
RADAR_FRAME_TOPIC = "radar/+/frame"  # NEW: Topic for radar frame data

# Postgres connection config (allow overriding host via POSTGRES_HOST)
PG_HOST = os.getenv("POSTGRES_HOST", "db")
PG_USER = os.getenv("POSTGRES_USER", "user")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")
PG_DB = os.getenv("POSTGRES_DB", "mqttdata")


async def init_db():
    conn = await asyncpg.connect(
        host=PG_HOST, user=PG_USER, password=PG_PASSWORD, database=PG_DB
    )
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS radarData (
            id SERIAL PRIMARY KEY,
            uuid VARCHAR(32),
            data BYTEA,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # NEW: Create radar_frames table for real-time calibration
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS radar_frames (
            id SERIAL PRIMARY KEY,
            radar_mac VARCHAR(32) NOT NULL,
            frame_number INT NOT NULL,
            angle FLOAT NOT NULL,
            range FLOAT NOT NULL,
            timestamp_ns BIGINT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed BOOLEAN DEFAULT FALSE
        );
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_radar_frames_name_timestamp
        ON radar_frames(radar_name, timestamp_ns);
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_radar_frames_processed
        ON radar_frames(processed);
    """)
    await conn.close()


async def process_message(pool, message):
    payload = json.loads(message.payload.decode())
    topic = str(message.topic)
    topic_parts = topic.split("/")
    uuid = topic_parts[1]
    data = payload["data"].encode("utf-8")
    print("processing message")
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO radarData (uuid, data) VALUES ($1, $2)", uuid, data
        )


async def process_frame_message(pool, message):
    """Process radar frame data for real-time calibration"""
    try:
        payload = json.loads(message.payload.decode())
        topic = str(message.topic)
        topic_parts = topic.split("/")
        radar_name = topic_parts[1]

        # Extract frame data
        frame_number = payload.get("frame", 0)
        angle = payload.get("angle", 0.0)
        range_m = payload.get("range", 0.0)
        timestamp_ns = payload.get("timestamp_ns", 0)

        print(
            f"Processing frame {frame_number} from {radar_name}: angle={angle:.1f}°, range={range_m:.2f}m"
        )

        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO radar_frames
                   (radar_name, frame_number, angle, range, timestamp_ns)
                   VALUES ($1, $2, $3, $4, $5)""",
                radar_name,
                frame_number,
                angle,
                range_m,
                timestamp_ns,
            )
    except Exception as e:
        print(f"Error processing frame message: {e}")


async def wait_for_db():
    while True:
        try:
            conn = await asyncpg.connect(
                host=PG_HOST, user=PG_USER, password=PG_PASSWORD, database=PG_DB
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
        host=PG_HOST, user=PG_USER, password=PG_PASSWORD, database=PG_DB
    )

    # Wait until the broker hostname resolves before attempting MQTT
    await wait_for_broker()

    try:
        print(f"Connecting to MQTT broker {BROKER}:{PORT}")
        print(f"  Subscribing to: {INPUT_TOPIC}")
        print(f"  Subscribing to: {RADAR_FRAME_TOPIC}")
        async with Client(BROKER, PORT) as client:
            await client.subscribe(INPUT_TOPIC)
            await client.subscribe(RADAR_FRAME_TOPIC)
            async for message in client.messages:
                topic = str(message.topic)
                if "/frame" in topic:
                    asyncio.create_task(process_frame_message(pool, message))
                else:
                    asyncio.create_task(process_message(pool, message))
    except MqttError as e:
        print(f"MQTT error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
