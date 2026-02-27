#!/bin/bash
sudo pkill -f setup_radar

pushd ../DCA1000/SourceCode/Release/
if ! sudo ./DCA1000EVM_CLI_Control reset_fpga DCAconfig.json; then
    sudo ./DCA1000EVM_CLI_Control stop_record DCAconfig.json
    sudo ./DCA1000EVM_CLI_Control reset_fpga DCAconfig.json
fi
popd