#!/bin/bash
# Multi-Radar Calibration Data Collection & Analysis
# ===================================================
# This script collects data from both Jetsons, combines it,
# runs calibration, and downloads results to your Mac.
#
# Usage: ./collect_radar_calibration.sh
#
# Prerequisites:
# 1. Both Jetsons have completed data collection (./test 100)
# 2. SSH access to both Jetsons is configured

echo "============================================"
echo "Multi-Radar Calibration Workflow"
echo "============================================"
echo ""

# Configuration
PATRICK_IP="169.231.215.235"
MIKE_IP="169.231.22.160"
PATRICK_DATA_PATH="~/Documents/Chirp/Node/test/non_thread/frame_data"
MIKE_DATA_PATH="~/Documents/Chirp/Node/test/non_thread/frame_data"
TEMP_DIR=~/Desktop/radar_temp_$(date +%Y%m%d_%H%M%S)
RESULT_DIR=~/Desktop/radar_results_$(date +%Y%m%d_%H%M%S)

# Create temp directory
mkdir -p $TEMP_DIR
cd $TEMP_DIR

echo "[1/5] Copying Patrick's data from $PATRICK_IP..."
if ! scp fusionsense@$PATRICK_IP:$PATRICK_DATA_PATH/Patrick_*.json . 2>/dev/null; then
    echo "[ERROR] Failed to copy Patrick's data"
    echo "Make sure:"
    echo "  1. Patrick's Jetson is accessible at $PATRICK_IP"
    echo "  2. Data collection has completed"
    echo "  3. Files exist at $PATRICK_DATA_PATH/Patrick_*.json"
    exit 1
fi

echo "[2/5] Copying Mike's data from $MIKE_IP..."
if ! scp fusionsense@$MIKE_IP:$MIKE_DATA_PATH/Mike_*.json . 2>/dev/null; then
    echo "[ERROR] Failed to copy Mike's data"
    echo "Make sure:"
    echo "  1. Mike's Jetson is accessible at $MIKE_IP"
    echo "  2. Data collection has completed"
    echo "  3. Files exist at $MIKE_DATA_PATH/Mike_*.json"
    exit 1
fi

# Count files
PATRICK_COUNT=$(ls Patrick_*.json 2>/dev/null | wc -l | tr -d ' ')
MIKE_COUNT=$(ls Mike_*.json 2>/dev/null | wc -l | tr -d ' ')
TOTAL_COUNT=$(ls *.json 2>/dev/null | wc -l | tr -d ' ')

echo ""
echo "=== Data Verification ==="
echo "Patrick: $PATRICK_COUNT frames"
echo "Mike: $MIKE_COUNT frames"
echo "Total: $TOTAL_COUNT frames"
echo ""

if [ "$PATRICK_COUNT" -eq 0 ] || [ "$MIKE_COUNT" -eq 0 ]; then
    echo "[ERROR] Missing data from one or both radars!"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Verify both Jetsons completed data collection"
    echo "  2. Check that ./test ran successfully on both"
    echo "  3. Verify frame_data/ directory contains JSON files"
    exit 1
fi

echo "[3/5] Uploading combined data to Patrick's Jetson..."
if ! scp *.json fusionsense@$PATRICK_IP:$PATRICK_DATA_PATH/ 2>/dev/null; then
    echo "[ERROR] Failed to upload combined data to Patrick"
    exit 1
fi
echo "✓ Upload complete!"

echo "[4/5] Running calibration on Patrick's Jetson..."
echo ""
if ! ssh fusionsense@$PATRICK_IP "cd $PATRICK_DATA_PATH && python3 ~/calibrate.py ." 2>/dev/null; then
    echo ""
    echo "[ERROR] Calibration failed"
    echo "Check that calibrate.py exists at ~/calibrate.py on Patrick's Jetson"
    exit 1
fi

echo ""
echo "[5/5] Downloading calibration results..."
if ! scp -r fusionsense@$PATRICK_IP:$PATRICK_DATA_PATH/calibration_output $RESULT_DIR 2>/dev/null; then
    echo "[ERROR] Failed to download results"
    echo "Calibration may have failed on Patrick's Jetson"
    exit 1
fi

echo ""
echo "============================================"
echo "✓ CALIBRATION COMPLETE!"
echo "============================================"
echo ""
echo "Results saved to: $RESULT_DIR"
echo ""

# Display results in terminal
if [ -f "$RESULT_DIR/calibration_results.txt" ]; then
    cat $RESULT_DIR/calibration_results.txt
    echo ""
else
    echo "[WARNING] calibration_results.txt not found"
fi

# List output files
echo "Output files:"
ls -lh $RESULT_DIR/ 2>/dev/null
echo ""

# Open results folder
if command -v open &> /dev/null; then
    echo "Opening results folder..."
    open $RESULT_DIR
fi

# Clean up temp files
echo ""
read -p "Delete temporary files in $TEMP_DIR? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf $TEMP_DIR
    echo "✓ Temporary files deleted."
else
    echo "Temporary files kept at: $TEMP_DIR"
fi

echo ""
echo "Done!"

