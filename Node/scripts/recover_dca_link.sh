#!/bin/bash

# Recover Jetson <-> DCA1000 Ethernet link without physical replug.
# Default values match current repo config, but can be overridden:
#   DCA_INTERFACE=enP8p1s0 JETSON_IP_CIDR=192.168.33.30/24 DCA_IP=192.168.33.180 bash recover_dca_link.sh

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (sudo)"
   exit 1
fi

set -u

INTERFACE="${DCA_INTERFACE:-enP8p1s0}"
JETSON_IP_CIDR="${JETSON_IP_CIDR:-192.168.33.30/24}"
DCA_IP="${DCA_IP:-192.168.33.180}"
PING_TRIES="${PING_TRIES:-2}"
PING_TIMEOUT_SEC="${PING_TIMEOUT_SEC:-1}"

print_status() {
    echo ""
    echo "------------------------------------------"
    echo "$1"
    echo "------------------------------------------"
}

require_cmd() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Error: required command not found: $cmd"
        exit 1
    fi
}

is_dca_reachable() {
    # DCA1000 does not respond to ICMP ping, but ARP still works.
    # Send a ping to trigger ARP resolution, then check the neighbor table.
    ping -c "$PING_TRIES" -W "$PING_TIMEOUT_SEC" "$DCA_IP" >/dev/null 2>&1
    ip neigh show dev "$INTERFACE" | grep -qE "$DCA_IP.*(REACHABLE|STALE|DELAY|PROBE)" 2>/dev/null
}

show_diag() {
    echo ""
    echo "Diagnostics:"
    ip -br addr show "$INTERFACE" 2>/dev/null || true
    ip -br link show "$INTERFACE" 2>/dev/null || true
    ip neigh show dev "$INTERFACE" 2>/dev/null | grep "$DCA_IP|FAILED|INCOMPLETE|STALE" || true
    arp -n | grep "$DCA_IP" || true
}

require_cmd ip
require_cmd ping
require_cmd nmcli
require_cmd ethtool
require_cmd arp
require_cmd grep

if ! ip link show "$INTERFACE" >/dev/null 2>&1; then
    echo "Error: interface '$INTERFACE' does not exist."
    echo "Tip: check with: ip -br link"
    exit 1
fi

print_status "DCA link pre-check"
echo "Interface: $INTERFACE"
echo "Jetson IP: $JETSON_IP_CIDR"
echo "DCA IP:    $DCA_IP"

if is_dca_reachable; then
    echo "DCA already reachable. No recovery needed."
    show_diag
    exit 0
fi

echo "DCA not reachable. Starting recovery sequence..."

print_status "Stopping stale radar processes"
pkill -f DCA1000EVM_CLI_Control >/dev/null 2>&1 || true
pkill -f setup_radar >/dev/null 2>&1 || true

print_status "Resetting NIC link state"
ip link set "$INTERFACE" down || { echo "Failed to set $INTERFACE down"; exit 1; }
sleep 1
ip link set "$INTERFACE" up || { echo "Failed to set $INTERFACE up"; exit 1; }

print_status "Re-applying interface IP and clearing neighbor cache"
ip addr replace "$JETSON_IP_CIDR" dev "$INTERFACE" || { echo "Failed to set IP $JETSON_IP_CIDR on $INTERFACE"; exit 1; }
ip neigh flush dev "$INTERFACE" >/dev/null 2>&1 || true

print_status "NetworkManager reconnect attempt"
nmcli device disconnect "$INTERFACE" >/dev/null 2>&1 || true
sleep 1
nmcli device connect "$INTERFACE" >/dev/null 2>&1 || true
sleep 2
# NetworkManager connect may clear the static IP; re-apply it.
ip addr replace "$JETSON_IP_CIDR" dev "$INTERFACE" || { echo "Failed to set IP $JETSON_IP_CIDR on $INTERFACE"; exit 1; }

print_status "Disabling EEE on interface (best effort)"
ethtool --set-eee "$INTERFACE" eee off >/dev/null 2>&1 || true

print_status "Post-recovery validation"
show_diag

if is_dca_reachable; then
    echo ""
    echo "Success: DCA ($DCA_IP) is reachable again."
    exit 0
fi

echo ""
echo "Recovery did not restore connectivity to $DCA_IP."
echo "Likely causes: DCA1000 is hard-hung, cable/connector issue, or DCA-side power/reset state."
echo "Next actions:"
echo "1) Try a DCA-side power/reset cycle."
echo "2) If still failing, re-seat cable or use a known-good cable."
echo "3) Re-run this script, then run reset/start commands."
exit 2
