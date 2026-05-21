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
echo "4) Convert Playback (option 3) Raw Data to .mat"
echo "5) Reset Radar"
echo "6) Exit"
echo "------------------------------------------"
read -p "Choice [1-6]: " test_choice

# Determine python executable
if [ -f "$NODE_DIR/.venv/bin/python3" ]; then
    PYTHON_EXEC="$NODE_DIR/.venv/bin/python3"
else
    PYTHON_EXEC="python3"
fi

# Load Node/.env into current shell if present.
load_node_env() {
    local env_file="$NODE_DIR/.env"
    if [ -f "$env_file" ]; then
        # shellcheck disable=SC1090
        set -a
        source "$env_file"
        set +a
    fi
}

# Ensure setup_radar build directory and executable exist
ensure_setup_radar_built() {
    local setup_radar_dir="$NODE_DIR/setup_radar"
    local build_dir="$setup_radar_dir/build"
    local setup_radar_bin="$build_dir/setup_radar"

    if [ ! -d "$setup_radar_dir" ]; then
        echo "Error: setup_radar directory not found at $setup_radar_dir"
        return 1
    fi

    echo ""
    echo ">>> Ensuring setup_radar is built..."
    if ! cmake -S "$setup_radar_dir" -B "$build_dir"; then
        echo "Error: CMake configure failed for setup_radar."
        return 1
    fi

    if ! cmake --build "$build_dir" --target setup_radar; then
        echo "Error: CMake build failed for setup_radar."
        return 1
    fi

    if [ ! -x "$setup_radar_bin" ]; then
        echo "Error: setup_radar executable not found after build at $setup_radar_bin"
        return 1
    fi
}

# Ensure selected hardware trigger executable exists (build on demand)
ensure_hardware_trigger_built() {
    local trigger_exe="$1"
    local trigger_dir="$NODE_DIR/src/hardware_trigger"

    if [ -z "$trigger_exe" ]; then
        echo "Error: No trigger executable path provided."
        return 1
    fi

    if [ -x "$trigger_exe" ]; then
        return 0
    fi

    if [ ! -d "$trigger_dir" ]; then
        echo "Error: Hardware trigger directory not found at: $trigger_dir"
        return 1
    fi

    echo "Hardware trigger executable not found at: $trigger_exe"
    echo "Attempting to build hardware triggers with Makefile..."
    if ! make -C "$trigger_dir"; then
        echo "Error: Failed to build hardware triggers in $trigger_dir"
        return 1
    fi

    if [ ! -x "$trigger_exe" ]; then
        echo "Error: Hardware trigger executable still missing after build: $trigger_exe"
        return 1
    fi
}

# Ensure MQTT trigger stack is ready for distributed mode.
ensure_mqtt_trigger_ready() {
    local mqtt_dir="$NODE_DIR/src/hardware_trigger_mqtt"
    local mqtt_client_py="$mqtt_dir/mqtt_trigger_client.py"
    local trigger_worker_bin="$mqtt_dir/trigger_worker"
    local missing_vars=()

    if [ ! -d "$mqtt_dir" ]; then
        echo "Error: MQTT trigger directory not found at $mqtt_dir"
        echo "Action: Create/build Phase 1-3 artifacts under src/hardware_trigger_mqtt first."
        return 1
    fi

    if [ ! -f "$mqtt_client_py" ]; then
        echo "Error: MQTT trigger client not found at $mqtt_client_py"
        echo "Action: Ensure Phase 2 created mqtt_trigger_client.py."
        return 1
    fi

    if [ ! -x "$trigger_worker_bin" ]; then
        echo "MQTT trigger worker missing at $trigger_worker_bin"
        echo "Attempting build with: make -C $mqtt_dir"
        if ! make -C "$mqtt_dir"; then
            echo "Error: Failed to build trigger_worker in $mqtt_dir"
            return 1
        fi
    fi

    if [ ! -x "$trigger_worker_bin" ]; then
        echo "Error: trigger_worker still missing after build: $trigger_worker_bin"
        return 1
    fi

    if [ -z "$MQTT_HOST" ]; then missing_vars+=("MQTT_HOST"); fi
    if [ -z "$MQTT_PORT" ]; then missing_vars+=("MQTT_PORT"); fi
    if [ -z "$NODE_ID" ]; then missing_vars+=("NODE_ID"); fi
    if [ -z "$GROUP_ID" ]; then missing_vars+=("GROUP_ID"); fi

    if [ ${#missing_vars[@]} -gt 0 ]; then
        echo "Error: Missing required environment variables for distributed MQTT trigger:"
        printf '  - %s\n' "${missing_vars[@]}"
        echo "Action: define them in $NODE_DIR/.env or export them before running this script."
        echo "Example:"
        echo "  export MQTT_HOST=127.0.0.1 MQTT_PORT=1883 NODE_ID=radar-orin-01 GROUP_ID=default"
        return 1
    fi

    if ! "$PYTHON_EXEC" -c "import paho.mqtt.client" >/dev/null 2>&1; then
        echo "Error: Python dependency missing: paho-mqtt"
        echo "Action: install dependencies with:"
        echo "  $PYTHON_EXEC -m pip install -r $NODE_DIR/requirements.txt"
        return 1
    fi

    if ! (echo >/dev/tcp/"$MQTT_HOST"/"$MQTT_PORT") 2>/dev/null; then
        echo "Warning: Cannot reach broker at $MQTT_HOST:$MQTT_PORT right now."
        echo "Action: verify broker is running and network/firewall allows TCP $MQTT_PORT."
        echo "Continuing anyway; mqtt_trigger_client.py will retry based on broker/client behavior."
    fi

    return 0
}

load_node_env

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
            ensure_setup_radar_built || exit 1
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
        echo "2) Distributed Triggering (networked_trigger - legacy)"
        echo "3) Distributed Triggering (MQTT trigger client)"
        echo "4) Skip Hardware Triggering"
        echo "------------------------------------------"
        read -p "Choice [1-4]: " trigger_choice

        TRIGGER_EXE=""
        MQTT_TRIGGER_CLIENT=""
        case $trigger_choice in
            1)
                TRIGGER_EXE="$NODE_DIR/src/hardware_trigger/local_trigger"
                ;;
            2)
                TRIGGER_EXE="$NODE_DIR/src/hardware_trigger/networked_trigger"
                ;;
            3)
                MQTT_TRIGGER_CLIENT="$NODE_DIR/src/hardware_trigger_mqtt/mqtt_trigger_client.py"
                ;;
            *)
                echo "Skipping hardware trigger."
                ;;
        esac

        # Start hardware trigger in background if selected
        if [ ! -z "$TRIGGER_EXE" ]; then
            ensure_hardware_trigger_built "$TRIGGER_EXE" || exit 1

            echo "Starting hardware trigger in background..."
            # Launch without sudo since script is already root
            "$TRIGGER_EXE" > /dev/null 2>&1 &
            TRIGGER_PID=$!
        fi

        # Start MQTT distributed trigger client in background if selected
        if [ ! -z "$MQTT_TRIGGER_CLIENT" ]; then
            ensure_mqtt_trigger_ready || exit 1

            echo "Starting MQTT trigger client in background..."
            "$PYTHON_EXEC" "$MQTT_TRIGGER_CLIENT" &
            TRIGGER_PID=$!
            sleep 2
            if ! kill -0 "$TRIGGER_PID" 2>/dev/null; then
                echo "Error: MQTT trigger client exited immediately (PID: $TRIGGER_PID)."
                echo "Action: run this command manually to inspect logs:"
                echo "  $PYTHON_EXEC $MQTT_TRIGGER_CLIENT"
                exit 1
            fi
            echo "MQTT trigger client is running (PID: $TRIGGER_PID)."
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
        echo ""
        echo ">>> Starting Playback Test from $DATA_DIR..."
        if [ -z "$(ls -A "$DATA_DIR/raw" 2>/dev/null)" ]; then
            echo "Error: $DATA_DIR/raw is empty. Run Data Capture first."
            exit 1
        fi

        read -p "Enter frame delay in ms [50]: " frame_delay_ms
        frame_delay_ms=${frame_delay_ms:-50}
        frame_delay_s=$(awk "BEGIN { printf \"%.3f\", $frame_delay_ms/1000 }")

        #echo ${frame_delay_s}
        $PYTHON_EXEC "$NODE_DIR/test/playback_test.py" --input-dir "$DATA_DIR/raw" --loop --delay "$frame_delay_s"
        ;;
    4)
        echo ""
        echo ">>> Converting Raw Data to .mat..."
        read -p "Enter input directory (default: $DATA_DIR/raw): " input_dir
        input_dir=${input_dir:-$DATA_DIR/raw}
        
        read -p "Enter output filename (default: $DATA_DIR/raw_data.mat): " output_file
        output_file=${output_file:-$DATA_DIR/raw_data.mat}
        
        $PYTHON_EXEC "$NODE_DIR/test/capture_data.py" --convert --input-dir "$input_dir" --output-file "$output_file" --type "raw"
        ;;
    5)
        echo ""
        echo "resetting radar"
        sudo bash $NODE_DIR/scripts/reset_radar.sh
        # Clear lockfile so next run re-initializes
        rm -f "/tmp/chirp_radar_status"
        ;;

    6)
        echo "Exiting."
        exit 0
        ;;

    *)
        echo "Invalid choice."
        exit 1
        ;;
esac
