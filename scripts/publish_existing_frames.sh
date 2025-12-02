#!/bin/bash
# Publish existing frame JSON files from Jetsons to MQTT
# Use this when you have pre-recorded data and don't need to run live radar

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load Jetson IPs from config
if [ ! -f "$SCRIPT_DIR/../.jetson_config" ]; then
    echo "Error: .jetson_config not found!"
    exit 1
fi

source "$SCRIPT_DIR/../.jetson_config"

SSH_USER="${SSH_USER:-fusionsense}"
MQTT_BROKER="${MQTT_BROKER:-169.231.217.90}"
MASTER_PASSWORD="${MASTER_PASSWORD:-fusionsense}"
SLAVE_PASSWORD="${SLAVE_PASSWORD:-password}"

echo "Publishing existing frame data from Jetsons to MQTT"
echo "MQTT Broker: $MQTT_BROKER"
echo ""

# Check if sshpass is available
USE_SSHPASS=false
if command -v sshpass &> /dev/null; then
    USE_SSHPASS=true
fi

# Publish from all Jetsons simultaneously
for name in Master Slave; do
    case $name in
        Master) 
            ip="$MASTER_IP"
            password="$MASTER_PASSWORD"
            ;;
        Slave) 
            ip="$SLAVE_IP"
            password="$SLAVE_PASSWORD"
            ;;
    esac
    
    echo "Publishing frames from $name ($ip)..."
    
    CMD="cd ~/Documents/Chirp/Node && python3 src/rpl/mqtt_publisher.py --broker $MQTT_BROKER --radar $name --once"
    
    if [ "$USE_SSHPASS" = true ]; then
        sshpass -p "$password" ssh -f -o StrictHostKeyChecking=no "$SSH_USER@$ip" "$CMD" &
    else
        ssh -f "$SSH_USER@$ip" "$CMD" &
    fi
done

wait

echo ""
echo "All frames published!"
echo ""
echo "Monitor calibration:"
echo "   docker logs -f calibration_processor"
echo ""
echo "Check database:"
echo "   docker exec postgres psql -U user -d mqttdata -c \"SELECT radar_name, COUNT(*), MAX(frame_number) FROM radar_frames GROUP BY radar_name;\""


