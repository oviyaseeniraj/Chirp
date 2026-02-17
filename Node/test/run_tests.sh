#!/bin/bash

# Interactive Test Runner for Chirp Radar Node

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
NODE_DIR="$( dirname "$SCRIPT_DIR" )"
DATA_DIR="$SCRIPT_DIR/data"

# Ensure Node/data exists
if [ ! -d "$DATA_DIR" ]; then
    echo "Creating data directory at $DATA_DIR"
    mkdir -p "$DATA_DIR"
fi

echo "=========================================="
echo "      Chirp Radar Test Runner             "
echo "=========================================="
echo "Select a test to run:"
echo "1) Full Integration Test (Live Radar + UI)"
echo "2) Data Capture (Save to Node/data)"
echo "3) Playback Test (Read from Node/data)"
echo "4) Exit"
echo "------------------------------------------"
read -p "Choice [1-4]: " test_choice

case $test_choice in
    1|2)
        # 1. Start Radar Hardware/FPGA
        echo ""
        echo ">>> Initializing Radar (requires sudo)..."
        sudo "$NODE_DIR/scripts/start_radar.sh"
        if [ $? -ne 0 ]; then
            echo "Failed to start radar. Exiting."
            exit 1
        fi

        # 2. Select Hardware Triggering
        echo ""
        echo ">>> Select Hardware Triggering Mode:"
        echo "1) Local Triggering (local_trigger)"
        echo "2) Distributed Triggering (networked_trigger)"
        echo "3) Skip Hardware Triggering"
        echo "------------------------------------------"
        read -p "Choice [1-3]: " trigger_choice

        TRIGGER_CMD=""
        case $trigger_choice in
            1)
                TRIGGER_CMD="sudo $NODE_DIR/src/hardware_trigger/local_trigger"
                ;;
            2)
                TRIGGER_CMD="sudo $NODE_DIR/src/hardware_trigger/networked_trigger"
                ;;
            *)
                echo "Skipping hardware trigger."
                ;;
        esac

        # Start hardware trigger in background if selected
        if [ ! -z "$TRIGGER_CMD" ]; then
            echo "Starting hardware trigger in background..."
            $TRIGGER_CMD > /dev/null 2>&1 &
            TRIGGER_PID=$!
            # Trap signals to ensure the trigger is killed when the script ends
            trap "echo 'Killing hardware trigger...'; sudo kill $TRIGGER_PID; exit" SIGINT SIGTERM
        fi

        # 3. Run selected test
        echo ""
        if [ "$test_choice" -eq 1 ]; then
            echo ">>> Starting Full Integration Test..."
            python3 "$NODE_DIR/test/full_integration_test.py"
        else
            echo ">>> Starting Data Capture (Target: $DATA_DIR)..."
            read -p "Enter number of frames to capture [100]: " frames
            frames=${frames:-100}
            python3 "$NODE_DIR/test/run_capture.py" --capture --frames "$frames" --output "$DATA_DIR"
        fi

        # Cleanup hardware trigger if it was started
        if [ ! -z "$TRIGGER_PID" ]; then
            echo "Stopping hardware trigger (PID: $TRIGGER_PID)..."
            sudo kill $TRIGGER_PID > /dev/null 2>&1
        fi
        ;;

    3)
        echo ""
        echo ">>> Starting Playback Test from $DATA_DIR..."
        if [ ! "$(ls -A $DATA_DIR)" ]; then
            echo "Error: $DATA_DIR is empty. Run Data Capture first."
            exit 1
        fi
        python3 "$NODE_DIR/test/playback_test.py" --input-dir "$DATA_DIR" --loop
        ;;

    4)
        echo "Exiting."
        exit 0
        ;;

    *)
        echo "Invalid choice."
        exit 1
        ;;
esac
