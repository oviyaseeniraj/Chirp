# Time Synchronization Setup (3-Node Configuration)

This setup supports 1 master and 2 slave Jetson nodes using Chrony NTP.

## SSH into Jetsons

```bash
# From your laptop - SSH into Master
ssh fusionsense@<MASTER_IP>

# From your laptop - SSH into Slave 1 (different terminal)
ssh fusionsense@<SLAVE1_IP>

# From your laptop - SSH into Slave 2 (different terminal)
ssh fusionsense@<SLAVE2_IP>
```

## Copy Scripts to Jetsons

```bash
# From your laptop - navigate to project directory
cd /path/to/Chirp/Time-Synchronization

# Copy setup script to Master
scp CHRONY_SETUP.sh fusionsense@<MASTER_IP>:~/

# Copy all files to Slave 1
scp CHRONY_SETUP.sh collect_offsets.py analyze_offsets.py requirements.txt fusionsense@<SLAVE1_IP>:~/

# Copy all files to Slave 2
scp CHRONY_SETUP.sh collect_offsets.py analyze_offsets.py requirements.txt fusionsense@<SLAVE2_IP>:~/

```

## Chrony Setup (Using Automated Script)

### On Master Jetson:
```bash
# Run the setup script
sudo ./CHRONY_SETUP.sh

# Select option 1 (Master/Server)

# Verify master is running
chronyc tracking
chronyc clients  # Should show connected slaves after they connect
```

### On Slave Jetson #1:
```bash
# Run the setup script
sudo ./CHRONY_SETUP.sh

# Select option 2 (Slave/Client #1)
# Enter the Master's IP address when prompted

# Wait 30 seconds, then verify
sleep 30
chronyc sources -v
chronyc tracking
```

### On Slave Jetson #2:
```bash
# Run the setup script
sudo ./CHRONY_SETUP.sh

# Select option 3 (Slave/Client #2)
# Enter the Master's IP address when prompted

# Wait 30 seconds, then verify
sleep 30
chronyc sources -v
chronyc tracking
```

## Run Data Collection Scripts

### Install Python Dependencies (on both slaves)
```bash
# Install Python dependencies via apt (RECOMMENDED for Jetson)
sudo apt-get update
sudo apt-get install -y python3-numpy python3-scipy python3-matplotlib

# Verify installation
python3 -c "import numpy, scipy, matplotlib; print('OK')"

# Make scripts executable
chmod +x collect_offsets.py analyze_offsets.py
```

### Collect Data from Slave #1
```bash
# On Slave Jetson #1
# Collect 100 samples at 1 second intervals with node identifier
python3 collect_offsets.py 100 1.0 slave1

# Note the output filename in data/jsons/, e.g., offset_data_20251106_194523.json
```

### Collect Data from Slave #2
```bash
# On Slave Jetson #2
# Collect 100 samples at 1 second intervals with node identifier
python3 collect_offsets.py 100 1.0 slave2

# Note the output filename in data/jsons/, e.g., offset_data_20251106_195523.json
```

### Analyze Individual Node Data
```bash
# Analyze data from a single slave
python3 analyze_offsets.py data/jsons/offset_data_20251106_194523.json

# Or with plots
python3 analyze_offsets.py data/jsons/offset_data_20251106_194523.json --plot
```

### Compare Multiple Nodes
```bash
# Compare offset performance between slave1 and slave2
python3 analyze_offsets.py --compare \
    data/jsons/offset_data_slave1_20251106_194523.json \
    data/jsons/offset_data_slave2_20251106_195523.json

# This will generate:
# - Statistical comparison (t-tests, mean differences)
# - Comparison plots (time series overlay, box plots, histograms, violin plots)
```

### Worst-Case Offset Analysis (Quick One-Liner)
```bash
# Get worst-case inter-device offset across entire network
python3 worst_case_offset.py data/jsons/offset_data_slave1_*.json data/jsons/offset_data_slave2_*.json

# This analyzes:
# - Individual node offset ranges from master
# - Maximum possible time difference between ANY two devices
# - Considers slave-to-slave AND slave-to-master comparisons
# - Reports the worst-case scenario (e.g., slave1 at +10ms when slave2 at -10ms = 20ms difference)

# Example output:
# WORST-CASE OFFSET BETWEEN ANY TWO DEVICES
# Maximum possible time difference: 150.5 μs (0.151 ms)
# Occurs between: slave1 and slave2
# ✓ System Status: EXCELLENT
```

### Copy Results Back to Laptop
```bash
# From your laptop - copy data from both slaves
scp fusionsense@<SLAVE1_IP>:~/data/jsons/offset_data_*.json ./slave1_data/
scp fusionsense@<SLAVE2_IP>:~/data/jsons/offset_data_*.json ./slave2_data/

# Copy plots if generated
scp fusionsense@<SLAVE1_IP>:~/data/histograms/*.png ./plots/
scp fusionsense@<SLAVE2_IP>:~/data/histograms/*.png ./plots/

# Then analyze/compare locally if needed
python3 analyze_offsets.py --compare slave1_data/*.json slave2_data/*.json
```

---

## Quick Test Commands

### On Master
```bash
# Check if chrony is running
systemctl status chrony

# View connected clients
chronyc clients

# View tracking info
chronyc tracking
```

### On Slaves
```bash
# Monitor sync status continuously
watch -n 1 'chronyc tracking'

# Check if master is reachable (look for ^ before master IP)
chronyc sources -v

# Check detailed source statistics
chronyc sourcestats

# Restart if needed
sudo systemctl restart chrony
```

### Troubleshooting
```bash
# If slave can't sync to master:
# 1. Check network connectivity
ping <MASTER_IP>

# 2. Check if chrony port (323/UDP) is accessible
sudo netstat -tulpn | grep chrony

# 3. Check chrony logs
sudo tail -f /var/log/syslog | grep chrony

# 4. Force time step if offset is large
sudo chronyc makestep

# 5. Restart chrony on both master and slave
sudo systemctl restart chrony
```
