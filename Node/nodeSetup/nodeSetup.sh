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
#TODO: Figure out where to 
# network setup
    # find ethernet device
    # dunno if all ethernets are eth0
    # ip addr add dev eth0 192.168.33.30/24
    # use nmcli connection ... https://wiki.archlinux.org/title/NetworkManager
# avahi setup

# Radar Permissions
# Chrony setup
