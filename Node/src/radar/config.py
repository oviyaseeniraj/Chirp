"""
Radar System Configuration
"""

import numpy as np

# Dimension Parameters
FAST_TIME = 512
SLOW_TIME = 64
RX = 4  # Number of receive antennas
TX = 3  # Number of transmit antennas
IQ = 2  # I and Q channels
IQ_BYTES = 2  # Bytes per IQ sample
BUFFER_SIZE = 2048

# Physical Parameters
CARRIER_FREQ = 77e9
SPEED_OF_LIGHT = 3e8
CHIRP_DURATION = 100e-6

# Computed Parameters
LAMBDA = SPEED_OF_LIGHT / CARRIER_FREQ
MAX_VELOCITY = LAMBDA / (4.0 * CHIRP_DURATION)
VELOCITY_RES = 2.0 * MAX_VELOCITY / SLOW_TIME

# Data Acquisition
PORT = 4098
BYTES_IN_PACKET = 1456
BYTES_IN_FRAME = SLOW_TIME * FAST_TIME * RX * TX * IQ * IQ_BYTES
BYTES_IN_FRAME_CLIPPED = (BYTES_IN_FRAME // BYTES_IN_PACKET) * BYTES_IN_PACKET

# Visualization
RANGE_ANGLE_PLOT_WIDTH = 400
RANGE_ANGLE_PLOT_HEIGHT = 300
