# 4-Node Radar Self-Calibration - Python Suite

Complete Python toolkit for multi-radar network calibration using closed-form solutions. Converted and enhanced from MATLAB with advanced analysis capabilities.

## Quick Start

```bash
# Install
cd "/Users/oseeniraj/Cellular Radar/mmSnap/Self-Calibration/Simulation/Single-Target"
pip install numpy matplotlib

# Run basic version
python3 closed_form_solution.py

# Run advanced version (Recommended)
python3 four_node_calibration.py

# Run demos
python3 demo_four_node.py
```

## Available Scripts

### 1. closed_form_solution.py
Direct MATLAB-to-Python conversion. Generates synthetic 4-radar data, performs closed-form calibration, creates 5 plots.

**Usage**: `python3 closed_form_solution.py`

### 2. four_node_calibration.py (Advanced)
Enhanced framework with multiple configurations (square, linear, L-shape, diamond), comprehensive error analysis, and comparison mode.

**Usage**: `python3 four_node_calibration.py`

### 3. demo_four_node.py
Interactive demos including noise sensitivity, trajectory length studies, and configuration comparisons.

**Usage**: `python3 demo_four_node.py`

## Installation

**Requirements**: Python 3.7+, NumPy 1.21+, Matplotlib 3.4+

```bash
pip install numpy matplotlib
```

Or with conda:
```bash
conda create -n radar_calibration python=3.9
conda activate radar_calibration
pip install numpy matplotlib
```

## Usage Examples

### Basic Usage

```bash
# Simple run with defaults
python3 four_node_calibration.py
# Press Enter twice for square configuration
```

### Interactive Menu

```bash
python3 four_node_calibration.py
```

Options:
- 1: Single configuration (choose square/linear/L-shape/diamond)
- 2: Compare all configurations
- 3: Custom configuration

### Programmatic API

```python
from four_node_calibration import FourNodeRadarCalibration

# Create and run
calibrator = FourNodeRadarCalibration(config='square')
results = calibrator.run_full_analysis(
    noise_std=0.5,
    measurement_noise_std=0.5,
    random_seed=42
)

# Access results
pos_errors = results['position_errors']
orient_errors = results['orientation_errors']
```

### Run Demos

```bash
python3 demo_four_node.py
```

Demo options:
1. Single configuration analysis
2. Compare different configurations
3. Noise sensitivity analysis
4. Trajectory length analysis
5. Run all demos
6. Full comparison mode

## Network Configurations

### Square (Default)
```
R2 -------- R3
|           |
|  Target   |
|           |
R1 -------- R4
```
Best for uniform coverage, highest accuracy.

### Linear
```
R1 --- R2 --- R3 --- R4
       Target
```
Best for highway/corridor tracking.

### L-Shape
```
R4
|
R1 --- R2 --- R3
       Target
```
Best for corner/junction monitoring.

### Diamond
```
      R3
     /  \
   R2    R4
     \  /
      R1
```
Best for central target tracking.

## Output

### Output Folder Structure

All plots are automatically saved to organized folders:

```
output/
├── basic_calibration_YYYYMMDD_HHMMSS/
│   ├── 01_ground_truth_square_config.png
│   ├── 02_calibration_radar1_reference.png
│   ├── 03_calibration_radar2_reference.png
│   ├── 04_calibration_radar3_reference.png
│   └── 05_calibration_radar4_reference.png
│
├── square_config_YYYYMMDD_HHMMSS/
│   ├── 01_ground_truth_square_config.png
│   ├── 02_square_calibration_radar1_reference.png
│   ├── 03_square_calibration_radar2_reference.png
│   ├── 04_square_calibration_radar3_reference.png
│   ├── 05_square_calibration_radar4_reference.png
│   └── 06_square_error_heatmaps_all_pairs.png
│
├── linear_config_YYYYMMDD_HHMMSS/
├── l-shape_config_YYYYMMDD_HHMMSS/
├── diamond_config_YYYYMMDD_HHMMSS/
│
├── comparison_YYYYMMDD_HHMMSS/
│   ├── config_comparison_summary.png
│   └── (individual config folders from above)
│
├── demo_noise_sensitivity_YYYYMMDD_HHMMSS/
│   └── noise_sensitivity_analysis.png
│
└── demo_trajectory_length_YYYYMMDD_HHMMSS/
    └── trajectory_length_analysis.png
```

Timestamp format: YYYYMMDD_HHMMSS (e.g., 20251016_143052)

**Note**: The `output/` directory is excluded from git tracking via `.gitignore`

### Console Output
```
============================================================
4-Node Radar Calibration Analysis
Configuration: SQUARE
============================================================

Calibration Error Statistics:
Position Errors:
  Mean:   1.234 m
  Std:    0.456 m
  Max:    2.345 m
  Min:    0.678 m

Orientation Errors:
  Mean:   2.345°
  Std:    1.234°
  Max:    4.567°
  Min:    0.890°
============================================================
```

### Plots Generated

**closed_form_solution.py**: 5 plots (ground truth + 4 calibration plots)

**four_node_calibration.py**: 6 plots per configuration
- Ground truth visualization
- 4 calibration plots (one per reference radar)
- Error summary heatmaps

**demo_four_node.py**: Varies by demo mode

## Customization

### Change Noise Levels

```python
results = calibrator.run_full_analysis(
    noise_std=1.0,              # Trajectory noise
    measurement_noise_std=0.2,   # Measurement noise
    random_seed=42
)
```

### Modify Time Steps

```python
calibrator = FourNodeRadarCalibration(config='square')
calibrator.num_iterations = 500  # Default is 100
results = calibrator.run_full_analysis()
```

### Custom Radar Configuration

```python
import numpy as np
calibrator = FourNodeRadarCalibration(config='square')

# Modify positions
calibrator.radar_position_array = np.array([
    [0, 50, 50, 0],      # X coordinates
    [0, 0, 50, 50]       # Y coordinates
])

# Modify orientations
calibrator.radar_orientation_array = np.array([45, 135, 225, 315])

# Update complex positions
calibrator.complex_radar_position_array = (
    calibrator.radar_position_array[0, :] + 
    1j * calibrator.radar_position_array[1, :]
)
```

### Accessing Saved Plots

All plots are automatically saved when you run any script. The output directory path is printed to console.

To find your plots:
1. Look for the console message: `Output Directory: output/...`
2. Navigate to that folder
3. All plots are saved as high-resolution PNGs (300 DPI)

To additionally save specific figures in custom locations:
```python
import matplotlib.pyplot as plt

calibrator.run_full_analysis()
# Additional save to custom location
plt.figure(1)
plt.savefig('/path/to/custom/location.png', dpi=300, bbox_inches='tight')
plt.show()
```

## Algorithm Overview

The closed-form calibration algorithm estimates relative positions and orientations between radar pairs using trajectory observations:

1. **Input**: Trajectory estimates from each radar in local coordinates
2. **Correlation**: Compute cross-correlation between radar observations
3. **Orientation Extraction**: Extract relative orientation from correlation phase
4. **Position Extraction**: Compute relative position using mean estimates
5. **Averaging**: Average results across all radar pairs for robustness
6. **Output**: Relative positions (complex) and orientations (degrees)

**Key Equations**:
- Correlation: `val = Σ (z_k(t) - mean_k) × conj(z_i(t) - mean_i)`
- Orientation: `θ_ki = -atan2(imag(val), real(val))`
- Position: `P_ki = mean_i - exp(-jθ) × mean_k`

## Feature Comparison

| Feature | closed_form | four_node | demo |
|---------|------------|-----------|------|
| Basic calibration | ✅ | ✅ | ✅ |
| Multiple configs | ❌ | ✅ | ✅ |
| Error analysis | ❌ | ✅ | ✅ |
| Interactive menu | ❌ | ✅ | ✅ |
| Noise studies | ❌ | ❌ | ✅ |
| Trajectory studies | ❌ | ❌ | ✅ |
| OOP design | ❌ | ✅ | ✅ |
| Comparison mode | ❌ | ✅ | ✅ |
| Heatmaps | ❌ | ✅ | ✅ |

## Troubleshooting

**Plots don't display**:
```bash
pip install tk
```

**Module not found**:
```bash
pip install --upgrade numpy matplotlib
```

**Too many plot windows**:
Save to files instead of displaying, or close windows one at a time.

**Running on remote server**:
```python
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
```

**Import errors after installation**:
```bash
python -m venv venv
source venv/bin/activate
pip install numpy matplotlib
```

## Tips

- **Iterations**: 100 (quick), 200-500 (good), 1000+ (high accuracy)
- **Noise**: 0.1 (ideal), 0.5 (realistic), 1.0+ (challenging)
- **Configuration**: Square typically performs best
- **Reproducibility**: Use fixed `random_seed=42`
- **Statistical analysis**: Run multiple times with different seeds

## Directory Structure

```
Single-Target/
├── closed_form_solution.py      (Basic MATLAB port)
├── four_node_calibration.py     (Advanced analysis)
├── demo_four_node.py            (Interactive demos)
├── requirements.txt             (Dependencies)
└── README.md                    (This file)
```

## Dependencies

```
numpy>=1.21.0
matplotlib>=3.4.0
```

## License

Same as parent project (mmSnap)

---

Version 1.0 | Python 3.7+ | Last Updated: October 16, 2025
