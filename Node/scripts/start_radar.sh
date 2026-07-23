#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DCA_DIR="$SCRIPT_DIR/../DCA1000/SourceCode/Release"
SETUP_RADAR_DIR="$SCRIPT_DIR/../setup_radar/build"

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (sudo)" 
   exit 1
fi


INTERFACE=$(nmcli device status | grep ethernet | awk '{print $1}' | head -n 1)
CONNECTION=$(nmcli -f NAME,TYPE connection show | grep ethernet | awk '{print $1}')
# Suppress output of ip check
if ! ip addr show $INTERFACE | grep -q "inet " > /dev/null 2>&1; then
   sudo nmcli connection up $CONNECTION > /dev/null 2>&1 || { echo "Failed to bring up nmcli connection $CONNECTION"; exit 1; }
fi

sudo sysctl -w net.core.rmem_max=16777216
sudo sysctl -w net.core.wmem_max=16777216

# make sure that system can find libRF_API.so by caching it in ldconfig
pushd "$DCA_DIR"
LD_LIBRARY_PATH=$(pwd)
export LD_LIBRARY_PATH
sudo ldconfig $(pwd) 2>/dev/null || true
popd

pushd "$SETUP_RADAR_DIR" > /dev/null 2>&1 || { echo "Failed to cd to $SETUP_RADAR_DIR"; exit 1; }
# Background process, output redirected also
./setup_radar < /dev/null
# nohup ./setup_radar > /dev/null 2>&1 < /dev/null &
echo -e "\n------------------------------------ \nignore the core dumped error message\n------------------------------------"
popd > /dev/null 2>&1

pushd "$DCA_DIR" > /dev/null 2>&1 || { echo "Failed to cd to $DCA_DIR"; exit 1; }
sudo ./DCA1000EVM_CLI_Control fpga DCAconfig.json || { echo "Failed to configure FPGA"; echo "if failing to configure FPGA, try running reset_radar(.sh) first"; exit 1; }
sudo ./DCA1000EVM_CLI_Control record DCAconfig.json || { echo "Failed to configure record mode"; exit 1; }
popd > /dev/null 2>&1


pushd "$DCA_DIR" > /dev/null 2>&1 || { echo "Failed to cd to $DCA_DIR (2nd time)"; exit 1; }
sudo ./DCA1000EVM_CLI_Control start_record DCAconfig.json -q || { echo "Failed to start_record"; exit 1; }
popd > /dev/null 2>&1