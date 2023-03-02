#!/bin/bash
# Publish radar frames to MQTT broker
# This script can be run on Jetson after data collection

# Configuration (Master node runs MQTT broker)
BROKER_IP="${MQTT_BROKER:-169.231.217.90}"
BROKER_PORT="${MQTT_PORT:-1883}"
FRAME_DIR="${FRAME_DIR:-/home/fusionsense/Documents/Chirp/Node/test/non_thread/frame_data}"

echo "============================================"
echo "MQTT Frame Publisher"
echo "============================================"
echo "Broker: $BROKER_IP:$BROKER_PORT"
echo "Frame directory: $FRAME_DIR"
echo ""

# Check if Python script exists
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLISHER_SCRIPT="$SCRIPT_DIR/../src/rpl/mqtt_publisher.py"

if [ ! -f "$PUBLISHER_SCRIPT" ]; then
    echo "Error: Publisher script not found at $PUBLISHER_SCRIPT"
    exit 1
fi

# Check if paho-mqtt is installed
if ! python3 -c "import paho.mqtt.client" 2>/dev/null; then
    echo "Installing paho-mqtt..."
    pip3 install paho-mqtt --user
fi

# Run publisher
python3 "$PUBLISHER_SCRIPT" \
    --broker "$BROKER_IP" \
    --port "$BROKER_PORT" \
    --watch-dir "$FRAME_DIR" \
    "$@"

