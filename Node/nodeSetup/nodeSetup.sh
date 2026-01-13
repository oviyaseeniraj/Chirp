#!/bin/bash
# script has been written to run on a jetson orin nano
# Make sure has sudo perms
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (sudo)" 
   exit 1
fi
# FTDI setup
pushd linux-arm-v8/  
sudo cp libftd2xx.* /usr/local/lib/  
chmod 0755 /usr/local/lib/libftd2xx.so.1.4.33  
ln -sf /usr/local/lib/libftd2xx.so.1.4.33 /usr/local/lib/libftd2xx.so  
cp ftd2xx.h /usr/local/include/  
cp WinTypes.h /usr/local/include/  
ldconfig -v
popd
    #TODO: setup FTDI rules
# Install dependencies
sudo apt install -y libfftw3-dev libopencv-dev libeigen3-dev libfmt-dev network-manager 
#TODO: Figure out where to make the symlinks for libraries if needed
# network setup
INTERFACE=$(nmcli device status | grep ethernet | awk '{print $1}' | head -n 1)
# sometimes the interface is unavailable, this is the only way I have found to make sure it works
sudo ip addr add dev $INTERFACE 192.168.33.30/24
sudo nmcli con mod $INTERFACE ipv4.addresses 192.168.33.30/24
# avahi setup

# Radar Permissions
# Chrony setup
