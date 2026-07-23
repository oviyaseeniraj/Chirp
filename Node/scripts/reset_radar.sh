#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DCA_DIR="$SCRIPT_DIR/../DCA1000/SourceCode/Release"

# make sure that system can find libRF_API.so by caching it in ldconfig 
# (redundant if already ran start_radar.sh, but good check to prevent future errors)
pushd "$DCA_DIR"
LD_LIBRARY_PATH=$(pwd)
export LD_LIBRARY_PATH
sudo ldconfig $(pwd)
popd

sudo pkill -f setup_radar

pushd "$DCA_DIR"
if ! sudo ./DCA1000EVM_CLI_Control reset_fpga DCAconfig.json; then
    sudo ./DCA1000EVM_CLI_Control stop_record DCAconfig.json
    sudo ./DCA1000EVM_CLI_Control reset_fpga DCAconfig.json
fi
popd