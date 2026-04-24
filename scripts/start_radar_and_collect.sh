#!/bin/bash
# Complete workflow: Start radar hardware and collect calibration data
# Usage: ./start_radar_and_collect.sh [num_frames]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NUM_FRAMES="${1:-100}"

# Load Jetson IPs
if [ ! -f "$SCRIPT_DIR/../.jetson_config" ]; then
    echo "Error: .jetson_config not found!"
    exit 1
fi

source "$SCRIPT_DIR/../.jetson_config"

SSH_USER="${SSH_USER:-fusionsense}"
MASTER_PASSWORD="${MASTER_PASSWORD:-fusionsense}"
SLAVE_PASSWORD="${SLAVE_PASSWORD:-password}"

USE_SSHPASS=false
if command -v sshpass &> /dev/null; then
    USE_SSHPASS=true
fi

echo "============================================"
echo "Complete Radar Calibration Workflow"
echo "============================================"
echo "Frames: $NUM_FRAMES"
echo ""

# Function to SSH with or without sshpass
run_ssh() {
    local ip=$1
    local password=$2
    local cmd=$3
    
    if [ "$USE_SSHPASS" = true ]; then
        sshpass -p "$password" ssh -o StrictHostKeyChecking=no "$SSH_USER@$ip" "$cmd"
    else
        ssh "$SSH_USER@$ip" "$cmd"
    fi
}

# Step 1: Start radar hardware on both Jetsons
echo "[1/4] Starting radar hardware..."
echo ""

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
    
    echo "  Starting $name ($ip)..."
    
    # Start DCA1000 and radar configuration in background
    run_ssh "$ip" "$password" "bash -c '
        cd ~/Documents/Chirp/Node/DCA1000/SourceCode/Release && 
        ./DCA1000EVM_CLI_Control &
        DCA_PID=\$!
        
        sleep 2
        
        cd ~/Documents/Chirp/Node/setup_radar/build &&
        ./setup_radar &&
        
        echo \"Radar hardware started (DCA PID: \$DCA_PID)\"
    '" 2>&1 | sed "s/^/    [$name] /" &
done

wait

echo ""
echo "[2/4] Waiting for radar initialization..."
sleep 5

# Step 2: Verify radar is streaming
echo "[3/4] Verifying radar data stream..."
for name in Master Slave; do
    case $name in
        Master) ip="$MASTER_IP"; password="$MASTER_PASSWORD" ;;
        Slave) ip="$SLAVE_IP"; password="$SLAVE_PASSWORD" ;;
    esac
    
    echo -n "  Checking $name... "
    if run_ssh "$ip" "$password" "timeout 3 sudo tcpdump -i any port 4098 -c 1 2>&1 | grep -q 'captured'" 2>/dev/null; then
        echo "OK (data streaming)"
    else
        echo "WARNING (no data detected, but continuing)"
    fi
done

echo ""
echo "[4/4] Starting data collection..."
echo ""

# Step 3: Trigger data collection
"$SCRIPT_DIR/start_all_jetsons.sh" "$NUM_FRAMES"

echo ""
echo "============================================"
echo "Data collection triggered!"
echo "============================================"
echo ""
echo "Monitor calibration:"
echo "  docker logs -f calibration_processor"
echo ""
echo "Check results:"
echo "  docker exec postgres psql -U user -d mqttdata -c \"SELECT * FROM calibration_results ORDER BY timestamp DESC LIMIT 5;\""


