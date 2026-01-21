#!/bin/bash
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (sudo)" 
   exit 1
fi


pushd ../DCA1000/SourceCode/Release/
sudo ./DCA1000EVM_CLI_Control fpga DCAconfig.json 
sudo ./DCA1000EVM_CLI_Control record DCAconfig.json
popd
pushd ../setup_radar/build/
sudo ./setup_radar &
popd
pushd ../DCA1000/SourceCode/Release/
sudo ./DCA1000EVM_CLI_Control start_record DCAconfig.json -q
popd