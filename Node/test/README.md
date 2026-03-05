## Quick Start

The recommended way to run tests is using the interactive test runner:
```bash
sudo bash run_tests.sh
```
This script orchestrates hardware initialization, trigger selection, and test execution (Integration, Capture, or Playback).

Important runnables:
| Script | Description | Usage |
| :--- | :--- | :--- |
| `run_tests.sh` | Main interactive test runner. Supports live tests, data capture, and **MATLAB conversion**. | `sudo ./run_tests.sh` |
| `capture_data.py` | CLI utility for capturing radar data (raw ADC + processed RDM) and converting to .mat. | `python3 capture_data.py --capture --frames 100 --output data` <br> `python3 capture_data.py --convert --input-dir data/raw --output-file data.mat --type raw` |
| `full_integration_test.py` | Full radar pipeline (DAQ -> Processing -> Visualizer) using live data. | `python3 full_integration_test.py` |
| `playback_test.py` | Full radar pipeline using recorded data from a directory. | `python3 playback_test.py --input-dir data/raw --loop` |


## Data Directory
The `data/` subdirectory is the default location for captured radar frames and the source for playback tests.
