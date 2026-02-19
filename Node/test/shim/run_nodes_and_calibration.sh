#!/bin/bash
# run_nodes_and_calibration.sh
# Launches main-newp3d.py on all available nodes and starts real-time spatial calibration on the local machine.

echo "\n--- Starting real-time spatial calibration on this machine ---"

# List of nodes (hostname:IP) - updated to tien1, tien2, tien4
NODES=(
  "tien1:169.231.200.9"
  "tien3:169.231.86.85"
  "tien4:169.231.105.114"
)

SCRIPT_PATH="main-newp3d.py"
NODE_USER="chirp"
NODE_PASS="chirp"


# Option 1: Use git to update code on each node before launching
GIT_REPO_PATH="Chirp"
GIT_BRANCH="radar_hardware_trigger"

for NODE in "${NODES[@]}"; do
  NODE_ID="${NODE%%:*}"
  IP="${NODE##*:}"
  echo -e "\n--- Connecting to $NODE_ID ($IP) ---"
  sshpass -p "$NODE_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 $NODE_USER@$IP \
    "cd $GIT_REPO_PATH && git switch $GIT_BRANCH && git pull && export NODE_ID=$NODE_ID; \
        
    cd Node/test/shim && \
    pwd && \
    nohup sudo ../../scripts/reset_radar.sh > ${NODE_ID}_reset_log.txt 2>&1 & \
    nohup sudo ../../scripts/start_radar.sh > ${NODE_ID}_start_log.txt 2>&1 & \
    nohup ./hardware_trigger/trigger_test > ${NODE_ID}_trigger_log.txt 2>&1 & \
    
    python3 -m venv .venv && \
    . .venv/bin/activate && \
    pwd
    pip install -r reqs.txt && \
    nohup python3 $SCRIPT_PATH > ${NODE_ID}_log.txt 2>&1 &" & \
done

# Wait a few seconds for nodes to start
sleep 5

echo -e "\n--- Starting real-time spatial calibration on this machine ---"
python3 spatial_calibration.py