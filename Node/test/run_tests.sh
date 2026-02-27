#!/bin/bash

# Interactive Test Runner for Chirp Radar Node

# Check for root privilege
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (sudo)" 
   exit 1
fi

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
NODE_DIR="$( dirname "$SCRIPT_DIR" )"
DATA_DIR="$SCRIPT_DIR/data"

# Ensure Node/data exists
if [ ! -d "$DATA_DIR" ]; then
    echo "Creating data directory at $DATA_DIR"
    mkdir -p "$DATA_DIR"
fi

# Function to cleanup child processes
cleanup() {
    echo ""
    echo "Caught signal! Cleaning up..."
    # Kill process group to ensure all children are dead
    trap - SIGINT SIGTERM # Disable trap to avoid recursion
    kill -- -$$ 2>/dev/null
    exit 1
}

# Trap SIGINT (Ctrl+C) and SIGTERM
trap cleanup SIGINT SIGTERM

echo "=========================================="
echo "      Chirp Radar Test Runner             "
echo "=========================================="
echo "Select a test to run:"
echo "1) Full Integration Test (Live Radar + UI)"
echo "2) Data Capture (Save to Node/data)"
echo "3) Playback Test (Read from Node/data)"
echo "4) Reset Radar"
echo "5) Exit"
echo "------------------------------------------"
read -p "Choice [1-5]: " test_choice

# Determine python executable
if [ -f "$NODE_DIR/.venv/bin/python3" ]; then
    PYTHON_EXEC="$NODE_DIR/.venv/bin/python3"
else
    PYTHON_EXEC="python3"
fi

case $test_choice in
    1|2)
        # 1. Check/Start Radar Hardware/FPGA
        RADAR_STATUS_FILE="/tmp/chirp_radar_status"
        
        if [ -f "$RADAR_STATUS_FILE" ]; then
            echo ""
            echo ">>> Radar already initialized (Lockfile found at $RADAR_STATUS_FILE). Skipping startup."
        else
            echo ""
            echo ">>> Initializing Radar (requires sudo)..."
            sudo bash "$NODE_DIR/scripts/start_radar.sh"
            if [ $? -ne 0 ]; then
                echo "Failed to start radar. Exiting."
                exit 1
            fi
            # Create lockfile to indicate radar is initialized
            touch "$RADAR_STATUS_FILE"
        fi

        # 2. Select Hardware Triggering
        echo ""
        echo ">>> Select Hardware Triggering Mode:"
        echo "1) Local Triggering (local_trigger)"
        echo "2) Distributed Triggering (networked_trigger)"
        echo "3) Skip Hardware Triggering"
        echo "------------------------------------------"
        read -p "Choice [1-3]: " trigger_choice

        TRIGGER_EXE=""
        case $trigger_choice in
            1)
                TRIGGER_EXE="$NODE_DIR/src/hardware_trigger/local_trigger"
                ;;
            2)
                TRIGGER_EXE="$NODE_DIR/src/hardware_trigger/networked_trigger"
                ;;
            *)
                echo "Skipping hardware trigger."
                ;;
        esac

        # Start hardware trigger in background if selected
        if [ ! -z "$TRIGGER_EXE" ]; then
            if [ ! -f "$TRIGGER_EXE" ]; then
                echo "Error: Hardware trigger executable not found at: $TRIGGER_EXE"
                echo "Please compile it first: (cd $NODE_DIR/src/hardware_trigger && make)"
                exit 1
            fi

            echo "Starting hardware trigger in background..."
            # Launch without sudo since script is already root
            "$TRIGGER_EXE" > /dev/null 2>&1 &
            TRIGGER_PID=$!
        fi

        # 3. Run selected test
        echo ""
        
        if [ "$test_choice" -eq 1 ]; then
            echo ">>> Starting UI server (Node/src/ui/server.py) in background:"
            $PYTHON_EXEC "$NODE_DIR/src/ui/server.py" > /dev/null 2>&1 &
            SERVER_PID=$!
            echo "Waiting for server on port 5001..."
            for _ in $(seq 1 15); do
                (echo >/dev/tcp/127.0.0.1/5001) 2>/dev/null && break
                sleep 1
            done
            if ! (echo >/dev/tcp/127.0.0.1/5001) 2>/dev/null; then
                echo "Warning: Server socket is not be ready yet. Proceeding with full integration test."
            fi
            
            echo ">>> Starting Full Integration Test"
            $PYTHON_EXEC "$NODE_DIR/test/full_integration_test.py"

            # Trap signals to ensure the hardware trigger and UI server (if any) are killed when the script ends
            trap 'echo "Killing hardware trigger..."; kill $TRIGGER_PID 2>/dev/null; [ -n "$SERVER_PID" ] && echo "Stopping UI server (PID: $SERVER_PID)..." && kill $SERVER_PID 2>/dev/null; exit' SIGINT SIGTERM
        
        else
            echo ">>> Starting Data Capture (Target: $DATA_DIR)..."
            read -p "Enter number of frames to capture [100]: " frames
            frames=${frames:-100}
            $PYTHON_EXEC "$NODE_DIR/test/capture_data.py" --capture --frames "$frames" --output "$DATA_DIR"
        fi

        # Cleanup hardware trigger if it was started
        if [ ! -z "$TRIGGER_PID" ]; then
            echo "Stopping hardware trigger (PID: $TRIGGER_PID)..."
            kill $TRIGGER_PID > /dev/null 2>&1
        fi
        # Automatic radar reset removed for persistence
        # sudo bash "$NODE_DIR/scripts/reset_radar.sh"
        ;;

    3)
        echo ""
        echo ">>> Starting Playback Test from $DATA_DIR..."
        if [ -z "$(ls -A "$DATA_DIR/raw" 2>/dev/null)" ]; then
            echo "Error: $DATA_DIR/raw is empty. Run Data Capture first."
            exit 1
        fi
        
        read -p "Visualize Clusters Only? (y/N): " clusters_only
        CLUSTERS_FLAG=""
        if [[ "$clusters_only" =~ ^[Yy]$ ]]; then
            CLUSTERS_FLAG="--clusters-only"
        fi

        $PYTHON_EXEC "$NODE_DIR/test/playback_test.py" --input-dir "$DATA_DIR/raw" --loop $CLUSTERS_FLAG
        ;;
    4)
        echo ""
        echo "resetting radar"
        sudo bash $NODE_DIR/scripts/reset_radar.sh
        # Clear lockfile so next run re-initializes
        rm -f "/tmp/chirp_radar_status"
        ;;

    5)
        echo "Exiting."
        exit 0
        ;;

    *)
        echo "Invalid choice."
        exit 1
        ;;
esac
