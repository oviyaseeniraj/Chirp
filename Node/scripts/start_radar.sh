#!/bin/bash
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (sudo)" 
   exit 1
fi

INTERFACE=$(nmcli device status | grep ethernet | awk '{print $1}' | head -n 1)
# Suppress output of ip check
if ! ip addr show $INTERFACE | grep -q "inet " > /dev/null 2>&1; then
   sudo nmcli connection up $INTERFACE > /dev/null 2>&1 || { echo "Failed to bring up nmcli connection $INTERFACE"; exit 1; }
fi

pushd ../setup_radar/build/ > /dev/null 2>&1 || { echo "Failed to cd to ../setup_radar/build/"; exit 1; }
# Background process, output redirected also
./setup_radar < /dev/null
# nohup ./setup_radar > /dev/null 2>&1 < /dev/null &
echo -e "\n------------------------------------ \nignore the core dumped error message\n------------------------------------"
popd > /dev/null 2>&1

pushd ../DCA1000/SourceCode/Release/ > /dev/null 2>&1 || { echo "Failed to cd to ../DCA1000/SourceCode/Release/"; exit 1; }
sudo ./DCA1000EVM_CLI_Control fpga DCAconfig.json || { echo "Failed to configure FPGA"; exit 1; }
sudo ./DCA1000EVM_CLI_Control record DCAconfig.json || { echo "Failed to configure record mode"; exit 1; }
popd > /dev/null 2>&1


pushd ../DCA1000/SourceCode/Release/ > /dev/null 2>&1 || { echo "Failed to cd to ../DCA1000/SourceCode/Release/ (2nd time)"; exit 1; }
sudo ./DCA1000EVM_CLI_Control start_record DCAconfig.json -q || { echo "Failed to start_record"; exit 1; }
popd > /dev/null 2>&1