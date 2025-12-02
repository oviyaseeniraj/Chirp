#!/bin/bash
# Chrony NTP Setup for Jetson Synchronization
# ============================================
# This is the RECOMMENDED approach for production use.

echo "================================"
echo "Chrony NTP Setup for Jetsons"
echo "================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "[ERROR] Please run as root (sudo)"
    exit 1
fi

# Install Chrony
echo "[1/4] Installing Chrony..."
apt-get update
apt-get install -y chrony

echo ""
echo "[2/4] Which Jetson is this?"
echo "  1) Master/Server (Primary time source)"
echo "  2) Slave/Client #1"
echo "  3) Slave/Client #2"
read -p "Enter choice [1-3]: " choice

if [ "$choice" = "1" ]; then
    echo ""
    echo "[3/4] Configuring as NTP Server..."
    
    cat > /etc/chrony/chrony.conf <<EOF
# Chrony NTP Server Configuration
# ================================

# Use system clock as reference (local mode)
local stratum 8
manual

# Allow clients on local network
allow 169.231.0.0/16

# Log directory
logdir /var/log/chrony

# Enable kernel synchronization
rtcsync

# Increase polling interval for stability
maxpoll 6

# Smooth time adjustments
smoothtime 400 0.001

# Step threshold (step if offset > 1 second)
makestep 1.0 3
EOF

    echo "[4/4] Starting Chrony server..."
    systemctl restart chrony
    systemctl enable chrony
    
    echo ""
    echo "=========================================="
    echo "✓ Master configured successfully!"
    echo "=========================================="
    echo ""
    echo "Verify with:"
    echo "  sudo chronyc sources"
    echo "  sudo chronyc clients"
    echo ""
    
elif [ "$choice" = "2" ] || [ "$choice" = "3" ]; then
    read -p "[3/4] Enter Master IP address: " master_ip
    
    if [ -z "$master_ip" ]; then
        echo "[ERROR] Master IP is required"
        exit 1
    fi
    
    echo ""
    echo "[4/4] Configuring as NTP Client (Slave #$((choice-1)))..."
    
    cat > /etc/chrony/chrony.conf <<EOF
# Chrony NTP Client Configuration (Slave #$((choice-1)))
# ================================

# Use local master as time source
server $master_ip iburst minpoll 0 maxpoll 4

# Fallback to internet NTP if local master unavailable
pool time.google.com iburst

# Log directory
logdir /var/log/chrony

# Enable kernel synchronization
rtcsync

# Allow larger adjustments for local network sync
maxdistance 10.0

# Smooth time adjustments
smoothtime 400 0.001

# Step threshold (step if offset > 1 second)
makestep 1.0 3
EOF

    echo "[4/4] Starting Chrony client..."
    systemctl restart chrony
    systemctl enable chrony
    
    echo ""
    echo "=========================================="
    echo "✓ Slave #$((choice-1)) configured successfully!"
    echo "=========================================="
    echo ""
    echo "Verify with:"
    echo "  sudo chronyc sources -v"
    echo "  sudo chronyc tracking"
    echo ""
    echo "Wait ~30 seconds for initial sync, then check offset:"
    echo "  watch -n 1 'chronyc tracking'"
    echo ""
    
else
    echo "[ERROR] Invalid choice"
    exit 1
fi

echo "Monitoring commands:"
echo "  chronyc sources    - Show time sources"
echo "  chronyc tracking   - Show sync status and offset"
echo "  chronyc sourcestats - Show source statistics"
echo ""

# Compile radar test executable
echo "=========================================="
echo "Compiling Radar Test Executable"
echo "=========================================="
echo ""

RADAR_DIR="/home/fusionsense/Documents/Chirp/Node/test/non_thread"

if [ -d "$RADAR_DIR" ]; then
    echo "Found radar directory at: $RADAR_DIR"
    echo "Compiling test executable..."
    
    cd $RADAR_DIR
    make clean
    make
    
    if [ -f "./test" ]; then
        echo "✓ Test executable compiled successfully!"
        echo ""
        echo "Test executable location: $RADAR_DIR/test"
    else
        echo "✗ Compilation failed. Check errors above."
    fi
else
    echo "✗ Radar directory not found at: $RADAR_DIR"
    echo "  Clone the repo first:"
    echo "    cd ~/Documents"
    echo "    git clone https://github.com/oviyaseeniraj/Chirp.git"
    echo "    cd Chirp && git checkout real-time"
fi

echo ""
echo "=========================================="
echo "Quick Setup Guide (3-Node Configuration):"
echo "=========================================="
echo ""
echo "On Master Jetson:"
echo "  sudo ./CHRONY_SETUP.sh"
echo "  Select: 1 (Master/Server)"
echo ""
echo "On Slave Jetson #1:"
echo "  sudo ./CHRONY_SETUP.sh"
echo "  Select: 2 (Slave/Client #1)"
echo "  Enter Master IP when prompted"
echo ""
echo "On Slave Jetson #2:"
echo "  sudo ./CHRONY_SETUP.sh"
echo "  Select: 3 (Slave/Client #2)"
echo "  Enter Master IP when prompted"
echo ""
echo "After all are configured, verify sync:"
echo "  On each Slave: chronyc tracking"
echo "  Look for offset < 1ms"
echo ""
echo "On Master, check connected clients:"
echo "  chronyc clients"
echo ""

