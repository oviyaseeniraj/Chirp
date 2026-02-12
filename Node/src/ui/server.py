import base64
import logging
import struct
import time
import os

import numpy as np
from flask import Flask, render_template
from flask_socketio import SocketIO, emit

from ..radar import config

# Disable all logging
logging.getLogger("werkzeug").disabled = True
logging.getLogger("socketio").disabled = True
logging.getLogger("engineio").disabled = True

# Specify template folder explicitly
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'templates'))
app = Flask(__name__, template_folder=template_dir)
app.config["SECRET_KEY"] = "fast-plotter3"

# Configuration
SHOW_RANGE_ANGLE_PLOT = True
RANGE_ANGLE_PLOT_WIDTH = 400
RANGE_ANGLE_PLOT_HEIGHT = 300

# RdBu colormap transition points (0-255)
TRANSITION_MID = 128  # Middle point (white)

# Pre-compute RdBu colormap lookup table once as a constant
COLORMAP = np.zeros((512, 3), dtype=np.uint8)
for i in range(256):
    if i < TRANSITION_MID:
        # Dark blue to white (first half)
        ratio = i / TRANSITION_MID
        red = int(0 + 255 * ratio)
        green = int(0 + 255 * ratio)
        blue = int(139 + (255 - 139) * ratio)
        COLORMAP[i] = [red, green, blue]
    else:
        # White to dark red (second half)
        ratio = (i - TRANSITION_MID) / (255 - TRANSITION_MID)
        red = int(255 - (255 - 139) * ratio)
        green = int(255 * (1 - ratio))
        blue = int(255 * (1 - ratio))
        COLORMAP[i] = [red, green, blue]


socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    logger=False,
    engineio_logger=False,
)


def array_to_raw_image(data_array):
    """Convert 64x256 array to 512x512 RGB image data"""
    # Normalize to 0-255 range
    normalized = (
        (data_array - data_array.min()) / (data_array.max() - data_array.min()) * 255
    ).astype(np.uint8)

    # Scale up from 64x256 to 512x512 using nearest neighbor interpolation
    # Repeat each row 8 times (512 / 64 = 8) and each column 2 times (512 / 256 = 2)
    scaled_array = np.repeat(np.repeat(normalized, 8, axis=0), 2, axis=1)
    scaled_array = np.rot90(scaled_array, k=1)

    # Create RGB image using colormap
    rgb_array = COLORMAP[scaled_array]

    return rgb_array


def encode_image_data(rgb_array):
    """Encode RGB array as base64 PNG-like data"""
    # Flatten and convert to bytes
    height, width, channels = rgb_array.shape

    # BMP header (54 bytes total)
    file_size = 54 + height * width * 3
    bitmap_header = struct.pack(
        "<2sIHHIIIIHHIIIIII",
        b"BM",  # Signature
        file_size,  # File size
        0,  # Reserved
        0,  # Reserved
        54,  # Offset to pixel data
        40,  # Header size
        width,  # Image width
        height,  # Image height
        1,  # Planes
        24,  # Bits per pixel
        0,  # Compression
        height * width * 3,  # Image size
        0,  # X pixels per meter
        0,  # Y pixels per meter
        0,  # Colors used
        0,  # Important colors
    )

    # BMP stores rows bottom-to-top, so flip the array
    flipped_rgb = np.flipud(rgb_array)

    # Convert to BGR format (BMP uses BGR instead of RGB)
    bgr_array = flipped_rgb[:, :, [2, 1, 0]]

    # Create the complete BMP file
    bmp_data = bitmap_header + bgr_array.tobytes()

    # Encode as base64
    return base64.b64encode(bmp_data).decode("ascii")


def extract_detections(cfar_array, angles_array, rdm_array=None):
    """Extract detection information from CFAR and angles arrays"""
    detections = []

    # Find detection positions
    detection_indices = np.where(cfar_array > 0)

    # Use constants from config if available, or define defaults
    # If not in config directly, define here based on known values
    # config.py was checked and lacks these derived physics constants
    # so we define them here locally or add to config. prefer local for now to avoid modifying config unnecessarily
    SLOW_TIME = config.SLOW_TIME
    CHIRP_DURATION = 100e-6
    # CARRIER_FREQ = 77e9 # config.py doesn't have it
    # SPEED_OF_LIGHT = 3e8
    # LAMBDA = SPEED_OF_LIGHT / CARRIER_FREQ
    
    # Actually, config.py MIGHT have LAMBDA?
    # Let's check config.py content from tool output.
    # It has LAMBDA = 3e8 / 77e9
    
    LAMBDA = config.LAMBDA
    MAX_VELOCITY = LAMBDA / (4.0 * CHIRP_DURATION)
    VELOCITY_RES = 2.0 * MAX_VELOCITY / SLOW_TIME

    for i in range(len(detection_indices[0])):
        doppler_idx = detection_indices[0][i]
        range_idx = detection_indices[1][i]

        # Get angle for this detection (0 means no angle estimate)
        angle_deg = angles_array[doppler_idx, range_idx]

        # Calculate velocity magnitude from doppler index
        # Center doppler bin at SLOW_TIME/2
        doppler_offset = doppler_idx - SLOW_TIME // 2
        velocity = doppler_offset * VELOCITY_RES  # in m/s

        # Get signal magnitude if RDM data is available
        magnitude = 0.0
        if rdm_array is not None:
            magnitude = float(rdm_array[doppler_idx, range_idx])

        # Convert indices to pixel coordinates (accounting for scaling and rotation)
        scaled_x = int(range_idx)  # column scaling
        scaled_y = int(doppler_idx * 8)  # row scaling

        # Apply 90-degree CCW rotation transformation
        # rot90(k=1) maps: (y, x) -> (x, height - y - 1)
        pixel_x = scaled_y
        pixel_y = 512 - scaled_x - 1

        detections.append(
            {
                "x": pixel_x,
                "y": pixel_y,
                "doppler_idx": int(doppler_idx),
                "range_idx": int(range_idx),
                "angle": float(angle_deg) if angle_deg != 0 else None,
                "velocity": float(velocity),
                "magnitude": magnitude,
            }
        )

    return detections


@app.route("/")
def index():
    return render_template(
        "index.html",
        show_range_angle_plot=SHOW_RANGE_ANGLE_PLOT,
        range_angle_plot_width=RANGE_ANGLE_PLOT_WIDTH,
        range_angle_plot_height=RANGE_ANGLE_PLOT_HEIGHT
    )


@socketio.on("send_frame")
def handle_array(data):
    """Process array data with angle overlay support"""
    try:
        start_time = time.time()

        # Convert RDM array data
        array_data = np.frombuffer(data["array"], dtype=np.float32)

        if array_data.size == 64 * 512:
            array_data = array_data.reshape(64, 512)

        if array_data.shape != (64, 512):
            print(f"Invalid array shape: {array_data.shape}")
            return

        # Process detections and angles if available
        detections = []
        if "angles" in data and "cfar" in data:
            try:
                angles_array = np.frombuffer(data["angles"], dtype=np.float32).reshape(
                    64, 512
                )
                cfar_array = np.frombuffer(data["cfar"], dtype=np.float32).reshape(
                    64, 512
                )

                if angles_array.shape == (64, 512) and cfar_array.shape == (64, 512):
                    # Use actual CFAR detections
                    detections = extract_detections(
                        cfar_array, angles_array, array_data
                    )
            except Exception as angle_error:
                print(f"Error processing angles/CFAR: {angle_error}")
        elif "angles" in data:
            try:
                angles_array = np.array(data["angles"], dtype=np.float32)
                if angles_array.shape == (64, 512):
                    # Fallback: create CFAR-like detection map from RDM data
                    threshold = np.mean(array_data) + 2 * np.std(array_data)
                    cfar_detections = (array_data > threshold).astype(np.uint8)
                    detections = extract_detections(
                        cfar_detections, angles_array, array_data
                    )
                    print(f"Found {len(detections)} detections with angles (fallback)")
            except Exception as angle_error:
                print(f"Error processing angles: {angle_error}")

        # Convert to image
        rgb_image = array_to_raw_image(array_data)
        image_data = encode_image_data(rgb_image)

        # Send to all clients
        emit(
            "radar_plot",
            {
                "image": image_data,
                "detections": detections,
            },
            broadcast=True,
        )

        # Performance logging
        process_time = (time.time() - start_time) * 1000
        if process_time > 5:  # Only log if it takes more than 5ms
            print(f"Frame processed in {process_time:.1f}ms")

    except Exception as e:
        print(f"Error processing array: {e}")


if __name__ == "__main__":
    print("Starting Radar Plotter with Angle Overlay on port 5001")
    socketio.run(app, host="0.0.0.0", port=5001, debug=False)
