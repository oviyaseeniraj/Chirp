#!/bin/bash
# Trigger data collection on all Jetsons simultaneously

set -e

# Configuration - Add your Jetson IPs and names here
declare -A JETSONS=(
    ["Master"]="169.231.217.90"     # Master node
    ["Slave"]="169.231.22.160"      # Slave node
    # ["Node3"]="169.231.xxx.xxx"   # Uncomment and add IP if you have more
    # ["Node4"]="169.231.xxx.xxx"   # Uncomment and add IP if you have more
)

SSH_USER="${SSH_USER:-fusionsense}"
NUM_FRAMES="${NUM_FRAMES:-100}"
TEST_DIR="~/Documents/Chirp/Node/test/non_thread"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "============================================================"
echo "Simultaneous Jetson Data Collection Trigger"
echo "============================================================"
echo ""

# Check if any Jetsons configured
if [ ${#JETSONS[@]} -eq 0 ]; then
    echo -e "${RED}Error: No Jetsons configured!${NC}"
    echo "Edit this script and add Jetson IPs to the JETSONS array"
    exit 1
fi

echo "Configured Jetsons:"
for name in "${!JETSONS[@]}"; do
    ip="${JETSONS[$name]}"
    echo "  - $name: $ip"
done
echo ""
echo "Frames to collect: $NUM_FRAMES"
echo ""

# Verify SSH connectivity
echo "Checking SSH connectivity..."
failed_jetsons=()
for name in "${!JETSONS[@]}"; do
    ip="${JETSONS[$name]}"
    if ssh -o ConnectTimeout=5 -o BatchMode=yes "$SSH_USER@$ip" "echo connected" &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $name ($ip)"
    else
        echo -e "  ${RED}✗${NC} $name ($ip) - SSH failed"
        failed_jetsons+=("$name")
    fi
done

if [ ${#failed_jetsons[@]} -gt 0 ]; then
    echo ""
    echo -e "${RED}Error: Cannot connect to: ${failed_jetsons[*]}${NC}"
    echo "Please check:"
    echo "  1. Jetson is powered on"
    echo "  2. Network connectivity"
    echo "  3. SSH key is configured"
    exit 1
fi

echo ""
echo -e "${GREEN}✓ All Jetsons reachable${NC}"
echo ""

# Clean old data (optional)
read -p "Clean old frame data before starting? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Cleaning old data..."
    for name in "${!JETSONS[@]}"; do
        ip="${JETSONS[$name]}"
        ssh "$SSH_USER@$ip" "rm -f $TEST_DIR/frame_data/*.json" &
    done
    wait
    echo -e "${GREEN}✓ Old data cleaned${NC}"
    echo ""
fi

# Countdown before starting
echo -e "${YELLOW}Starting data collection in:${NC}"
for i in {3..1}; do
    echo "  $i..."
    sleep 1
done
echo ""

# Create timestamp for synchronized start
START_TIME=$(date +%s)

echo "============================================================"
echo "TRIGGERING DATA COLLECTION ON ALL JETSONS"
echo "============================================================"
echo ""

# Array to store background PIDs
pids=()

# Trigger all Jetsons simultaneously in background
for name in "${!JETSONS[@]}"; do
    ip="${JETSONS[$name]}"
    
    echo "Starting $name ($ip)..."
    
    # SSH and run test in background
    ssh "$SSH_USER@$ip" "cd $TEST_DIR && ./test $NUM_FRAMES" &
    pids+=($!)
    
    # Small delay to stagger SSH connections
    sleep 0.1
done

echo ""
echo "✓ All Jetsons triggered"
echo "Waiting for data collection to complete..."
echo ""

# Wait for all background processes
failed=0
for i in "${!pids[@]}"; do
    pid=${pids[$i]}
    name="${!JETSONS[@]:$i:1}"
    
    if wait $pid; then
        echo -e "  ${GREEN}✓${NC} $name completed"
    else
        echo -e "  ${RED}✗${NC} $name failed (exit code $?)"
        ((failed++))
    fi
done

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "============================================================"

if [ $failed -eq 0 ]; then
    echo -e "${GREEN}✓ All Jetsons completed successfully${NC}"
else
    echo -e "${YELLOW}⚠ $failed Jetson(s) failed${NC}"
fi

echo "Total time: ${DURATION}s"
echo "============================================================"
echo ""

# Optional: Automatically publish frames to MQTT
read -p "Publish frames to MQTT for real-time calibration? [Y/n] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    echo ""
    echo "Starting MQTT publishers on all Jetsons..."
    
    for name in "${!JETSONS[@]}"; do
        ip="${JETSONS[$name]}"
        echo "  Starting publisher on $name..."
        
        # Start publisher in background on Jetson
        ssh "$SSH_USER@$ip" "cd ~/Documents/Chirp/Node && ./scripts/mqtt_publish_frames.sh --once &" &
    done
    
    wait
    
    echo ""
    echo -e "${GREEN}✓ MQTT publishing started on all Jetsons${NC}"
    echo ""
    echo "Monitor calibration:"
    echo "  docker logs -f calibration_processor"
fi

echo ""
echo "Done!"

