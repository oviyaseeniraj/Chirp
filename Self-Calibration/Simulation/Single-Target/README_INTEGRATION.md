# Minimal C++ to Python Calibration Integration

Ultra-simple integration: C++ collects data → Saves to JSON files → Python calibrates → Done.

**No network communication required** - everything is file-based.

## Complete Setup Guide for Jetson (Git-Based Workflow)

### Step 0: Time Synchronization (CRITICAL for Multi-Radar Calibration)

Time sync is **essential** for accurate calibration when using multiple radars. The frames must be time-aligned.

**On Patrick's Jetson (169.231.215.235) - Master:**
```bash
ssh fusionsense@169.231.215.235
cd ~/Documents/Chirp/Time-Synchronization
sudo ./CHRONY_SETUP.sh
# Select: 1 (Master/Server)
```

**On Mike's Jetson (169.231.22.160) - Client:**
```bash
ssh fusionsense@169.231.22.160
cd ~/Documents/Chirp/Time-Synchronization
sudo ./CHRONY_SETUP.sh
# Select: 2 (Slave/Client)
# Press Enter to use Patrick (169.231.215.235) as master
```

**Verify synchronization on Mike's Jetson:**
```bash
chronyc tracking
# Look for: "System time     : 0.000XXX seconds slow/fast of NTP time"
# Offset should be < 1ms (0.001 seconds)
```

### Step 1: Clone/Update Git Repository on Jetson

SSH to Jetson and sync the repository:

```bash
ssh fusionsense@169.231.215.235

# If repo doesn't exist, clone it first
cd ~/Documents
git clone https://github.com/oviyaseeniraj/Chirp.git

# Navigate to repo and checkout the branch
cd ~/Documents/Chirp
git checkout real-time
git pull origin real-time
```

### Step 2: Copy Calibration Script to Jetson

From your **Mac Terminal**:

```bash
# Copy calibrate.py to Jetson home directory
scp /Users/oseeniraj/Chirp/Self-Calibration/Simulation/Single-Target/calibrate.py \
    fusionsense@169.231.215.235:~/
```

### Step 3: Install Dependencies on Jetson (If Needed)

SSH to Jetson and install required libraries:

```bash
ssh fusionsense@169.231.215.235

# Install Python dependencies (use apt-get, not pip3)
sudo apt-get update
sudo apt-get install python3-numpy python3-matplotlib -y

# Install C++ dependencies
sudo apt-get install libeigen3-dev rapidjson-dev -y

# Create Eigen symlink (required for compilation)
sudo ln -s /usr/include/eigen3/Eigen /usr/include/Eigen

# Verify Python dependencies
python3 -c 'import numpy; import matplotlib; print("Dependencies OK")'
```

### Step 3b: Create Desktop Helper Script (Optional)

Create a convenient script on the Jetson Desktop for easy testing:

```bash
# Create the script
cat > ~/Desktop/run_test.sh << 'EOF'
#!/bin/bash
cd ~/Documents/Chirp/Node/test/non_thread

# Run test with logging (default 100 frames if no argument provided)
if [ $# -eq 0 ]; then
    ./test 100 2>&1 | tee test_output.log
else
    ./test "$@" 2>&1 | tee test_output.log
fi

echo ""
echo "Output saved to: ~/Documents/Chirp/Node/test/non_thread/test_output.log"
echo "Data saved to: ~/Documents/Chirp/Node/test/non_thread/frame_data/"
echo "Results in: ~/Documents/Chirp/Node/test/non_thread/frame_data/calibration_output/"
EOF

# Make it executable
chmod +x ~/Desktop/run_test.sh

echo "Desktop script created! Run with: ~/Desktop/run_test.sh [num_frames]"
```

### Step 4: Compile on Jetson

```bash
# Navigate to test directory
cd ~/Documents/Chirp/Node/test/non_thread

# Compile test.cpp with calibration support (or just use 'make')
make

# Or compile directly:
# g++ -std=c++14 -Wall -Wextra -pedantic -I../../src/ -o test test.cpp \
#     -lfftw3f -pthread -lm `pkg-config --cflags --libs opencv4`
```

### Step 5: Run Data Collection & Calibration

```bash
# Option 1: Use the desktop script
~/Desktop/run_test.sh          # Runs 100 frames (default)
~/Desktop/run_test.sh 200      # Runs 200 frames

# Option 2: Run directly
./test 100
```

The program will:
1. Collect radar data (angle/range per frame)
2. Save JSON files to `frame_data/`
3. Automatically run Python calibration
4. Save results to `frame_data/calibration_output/`

### Step 6: View Results on Jetson

```bash
# View calibration results
cat ~/Documents/Chirp/Node/test/non_thread/frame_data/calibration_output/calibration_results.txt

# List all output files
ls -la ~/Documents/Chirp/Node/test/non_thread/frame_data/calibration_output/
```

### Step 7: Copy Results to Your Mac

From your **Mac Terminal**:

```bash
# Copy results to your Desktop
scp -r fusionsense@169.231.215.235:~/Documents/Chirp/Node/test/non_thread/frame_data/calibration_output \
    ~/Desktop/radar_results

# Open the folder to view plots
open ~/Desktop/radar_results
```

## What the Code Does

**Input**: JSON files with `Angle` and `Range` from each radar node  
**Process**: Converts polar→Cartesian, runs closed-form calibration algorithm  
**Output**: `frame_data/calibration_output/`
- `calibration_results.txt` - relative positions & orientations
- `calibration_{NodeName}.png` - visualization plots for each radar

## Example Output

```
RADAR CALIBRATION RESULTS
============================================================

Patrick as Reference:
--------------------------------------------------
  Mike: Position=(40.00, 0.00)m, Orientation=90.0°
  John: Position=(40.00, 40.00)m, Orientation=180.0°
  Sarah: Position=(0.00, 40.00)m, Orientation=270.0°
```

## Files Modified

- **calibrate.py** - Standalone Python script (reads JSON files, runs calibration, saves plots)
  - Uses `matplotlib.use('Agg')` for headless operation on Jetson
  - Compatible with older matplotlib versions (2.1.1)
- **test.cpp** - Modified to collect fixed frames + call calibration
  - Collects 100 frames by default (configurable via command line)
- **implementation.cpp** - Simplified to file-only operation
  - `process()` writes JSON files locally (no network communication)
  - `run_calibration()` calls Python script with data directory
  - Removed TCP/UDP socket code for simpler operation

## Troubleshooting

**Compilation fails with "Eigen/Dense not found"**
```bash
sudo ln -s /usr/include/eigen3/Eigen /usr/include/Eigen
```

**Compilation fails with "rapidjson/document.h not found"**
```bash
sudo apt-get install rapidjson-dev -y
```

**Python script fails with "No module named numpy"**
```bash
sudo apt-get install python3-numpy python3-matplotlib -y
```

**No JSON files found**
```bash
# Make sure frame_data directory exists
mkdir -p ~/Documents/Chirp/Node/test/non_thread/frame_data
```

**"Bad file descriptor" error during data collection**
- This was from the old TCP/UDP network code
- Make sure you have the latest `implementation.cpp` that uses file-only mode
- Pull latest from git and re-compile: `git pull origin real-time && make clean && make`

## Manual Testing

Test calibration on existing data without running radar:

```bash
python3 /home/fusionsense/calibrate.py /path/to/data_directory
```

## Jetson Info

- **Jetson IP**: `169.231.215.235`
- **Username**: `fusionsense`
- **Git Repo**: `~/Documents/Chirp` (branch: `real-time`)
- **Test Path**: `~/Documents/Chirp/Node/test/non_thread`
- **Data Path**: `~/Documents/Chirp/Node/test/non_thread/frame_data`
- **Calibration Script**: `/home/fusionsense/calibrate.py`

## Quick Reference - Git-Based Workflow

### Single Jetson Testing:
```bash
# 1. On Jetson: Update code from git
ssh fusionsense@169.231.215.235
cd ~/Documents/Chirp
git pull origin real-time

# 2. Copy calibrate.py from Mac (if updated)
# (From Mac Terminal)
scp /Users/oseeniraj/Chirp/Self-Calibration/Simulation/Single-Target/calibrate.py fusionsense@169.231.215.235:~/

# 3. On Jetson: Compile and run
cd ~/Documents/Chirp/Node/test/non_thread
make clean && make
./test 100

# Or use the desktop script:
~/Desktop/run_test.sh 100

# 4. Copy results back to Mac
# (From Mac Terminal)
scp -r fusionsense@169.231.215.235:~/Documents/Chirp/Node/test/non_thread/frame_data/calibration_output ~/Desktop/radar_results
open ~/Desktop/radar_results
```

### Multi-Radar Calibration (Automated):

**Step 1: Start data collection on both Jetsons**
```bash
# Terminal 1 - Patrick (169.231.215.235)
ssh fusionsense@169.231.215.235
cd ~/Documents/Chirp/Node/test/non_thread
rm -f frame_data/*.json && ./test 100

# Terminal 2 - Mike (169.231.22.160) - start simultaneously
ssh fusionsense@169.231.22.160
cd ~/Documents/Chirp/Node/test/non_thread
rm -f frame_data/*.json && ./test 100
```

**Step 2: After both finish, run the automated script on your Mac**
```bash
# One command does everything!
cd /Users/oseeniraj/Chirp/Self-Calibration/Simulation/Single-Target
./collect_radar_calibration.sh
```

The script automatically:
- ✅ Copies Patrick's data from 169.231.215.235
- ✅ Copies Mike's data from 169.231.22.160
- ✅ Verifies both datasets
- ✅ Combines and uploads to Patrick
- ✅ Runs calibration remotely
- ✅ Downloads results with timestamp
- ✅ Opens results folder

