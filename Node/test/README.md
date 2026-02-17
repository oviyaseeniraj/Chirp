## Quick Start

The recommended way to run tests is using the interactive test runner:
```bash
./run_tests.sh
```
This script orchestrates hardware initialization, trigger selection, and test execution (Integration, Capture, or Playback).

| Script | Description | Usage |
| :--- | :--- | :--- |
| `run_capture.py` | CLI utility for capturing radar data (raw ADC + processed RDM). | `python3 run_capture.py --capture --frames 100 --output data` |
| `full_integration_test.py` | Full radar pipeline (DAQ -> Processing -> Visualizer) using live data. | `python3 full_integration_test.py` |
| `playback_test.py` | Full radar pipeline using recorded data from a directory. | `python3 playback_test.py --input-dir data --loop` |

## Data Directory
The `data/` subdirectory is the default location for captured radar frames and the source for playback tests.
