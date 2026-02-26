#!/bin/bash
# run_nodes_and_calibration.sh
# Launches main-newp3d.py on all available nodes and starts real-time spatial calibration on the local machine.

echo "\n--- Starting radar data collection on all nodes ---"

# List of nodes (hostname:IP) - Running nodes: tien4, tien1
NODES=(
  "tien4:169.231.105.114"
  "tien1:169.231.202.62"
)

SCRIPT_PATH="/Users/oseeniraj/Chirp-1/Node/test/shim/main-newp3d.py"
NODE_USER="chirp"
NODE_PASS="chirp"


# Option 1: Use git to update code on each node before launching
GIT_REPO_PATH="Chirp"
GIT_START_RADAR_PATH="Node/scripts"
GIT_BRANCH="radar_hardware_trigger"

for NODE in "${NODES[@]}"; do
  NODE_ID="${NODE%%:*}"
  IP="${NODE##*:}"
  echo -e "\n--- Connecting to $NODE_ID ($IP) ---"
  sshpass -p "$NODE_PASS" ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no -o StrictHostKeyChecking=no -o ConnectTimeout=10 $NODE_USER@$IP \
    "cd $GIT_REPO_PATH && git switch $GIT_BRANCH && git pull && export NODE_ID=$NODE_ID; cd Node/setup_radar && echo $NODE_PASS | sudo -S bash setup_radar.sh && cd ../scripts && echo $NODE_PASS | sudo -S bash start_radar.sh && cd ../test/shim && nohup python3 hardware_trigger/trigger_test > ${NODE_ID}_trigger.txt 2>&1 & sleep 2 && nohup python3 $SCRIPT_PATH > ${NODE_ID}_log.txt 2>&1 &" &
done

# Wait for 100 frames from each node (poll for completion)
echo "Waiting for 100 frames from each node..."
NODE_IDS=("tien4" "tien1")
FRAME_TARGET=100
while true; do
  ALL_DONE=true
  for NODE_ID in "${NODE_IDS[@]}"; do
    DATA_FILE="/home/chirp/Chirp/Node/test/shim/calibration_data_${NODE_ID}.pkl"
    COUNT=0
    if sshpass -p "$NODE_PASS" ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no -o StrictHostKeyChecking=no -o ConnectTimeout=10 $NODE_USER@${NODE_ID} "python3 -c 'import pickle; f=\"$DATA_FILE\"; import os; print(len(pickle.load(open(f, \"rb\")) if os.path.exists(f) else {{}}))'" 2>/dev/null | grep -q "^$FRAME_TARGET$"; then
      echo "$NODE_ID: 100 frames collected."
    else
      echo "$NODE_ID: waiting for frames..."
      ALL_DONE=false
    fi
  done
  if $ALL_DONE; then
    break
  fi
  sleep 10
done

echo "\n--- All nodes have collected 100 frames. Running spatial calibration...\n"
python3 /Users/oseeniraj/Chirp-1/Node/test/shim/spatial_calibration.py
