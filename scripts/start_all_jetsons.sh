#!/bin/bash
# Simple one-command trigger for all Jetsons
# Usage: ./start_all_jetsons.sh [num_frames]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NUM_FRAMES="${1:-100}"

# Load Jetson IPs from config
if [ ! -f "$SCRIPT_DIR/../.jetson_config" ]; then
    echo "Error: .jetson_config not found!"
    exit 1
fi

source "$SCRIPT_DIR/../.jetson_config"

SSH_USER="${SSH_USER:-fusionsense}"
MQTT_BROKER="${MQTT_BROKER:-localhost}"

# Passwords (if SSH keys not set up)
MASTER_PASSWORD="${MASTER_PASSWORD:-fusionsense}"
SLAVE_PASSWORD="${SLAVE_PASSWORD:-password}"

echo "Starting all Jetsons with $NUM_FRAMES frames..."
echo ""

# Check if sshpass is available
USE_SSHPASS=false
if command -v sshpass &> /dev/null; then
    USE_SSHPASS=true
    echo "Note: Using sshpass for authentication"
    echo ""
fi

# Trigger all Jetsons simultaneously
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
    
    echo "Triggering $name ($ip)..."
    
    # Build command to run test with virtual display (works with or without xvfb)
    CMD="bash -c '
        cd ~/Documents/Chirp/Node/test/non_thread && 
        chmod +x ./test 2>/dev/null;
        if command -v xvfb-run >/dev/null 2>&1; then
            xvfb-run -a ./test $NUM_FRAMES
        else
            ./test $NUM_FRAMES 2>&1 | grep -v \"Gtk-WARNING\"
        fi && 
        cd ~/Documents/Chirp/Node && 
        python3 src/rpl/mqtt_publisher.py --broker $MQTT_BROKER --radar $name --once
    '"
    
    # Start data collection AND MQTT publishing in one command
    if [ "$USE_SSHPASS" = true ]; then
        sshpass -p "$password" ssh -f -o StrictHostKeyChecking=no "$SSH_USER@$ip" "$CMD" &
    else
        ssh -f "$SSH_USER@$ip" "$CMD" &
    fi
done

wait

echo ""
echo "All Jetsons triggered!"
echo ""
echo "Monitor calibration:"
echo "   docker logs -f calibration_processor"
echo ""
echo "Check database:"
echo "   docker exec postgres psql -U user -d mqttdata -c \"SELECT radar_name, COUNT(*), MAX(frame_number) FROM radar_frames GROUP BY radar_name;\""

