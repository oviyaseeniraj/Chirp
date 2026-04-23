#!/bin/bash
echo "--- JETSON NETWORK AUDIT ---"
echo "Hostname: $(hostname)"
echo "Interface: enP8p1s0"
echo "----------------------------"

echo "[1] Interface State & MTU"
ip link show enP8p1s0 | grep mtu

echo -e "\n[2] UDP Receive Buffers"
sysctl net.core.rmem_max
sysctl net.core.rmem_default
sysctl net.core.netdev_max_backlog

echo -e "\n[3] Offloading Features"
ethtool -k enP8p1s0 | grep -E 'receive-offload|udp-fragmentation-offload'

echo -e "\n[4] Interrupt Coalescing"
ethtool -c enP8p1s0 | grep -E 'rx-usecs|rx-frames'

echo -e "\n[5] Ring Buffer Sizes"
ethtool -g enP8p1s0 | grep -A 1 "Current hardware"

echo -e "\n[6] PCIe ASPM Status"
sudo lspci -vvv -s $(lspci | grep Ethernet | cut -d' ' -f1) | grep ASPM

echo -e "\n[7] Power & Clocks"
nvpmodel -q
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
