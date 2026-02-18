import base64
import logging
import time
import sys
import os
import numpy as np
import cv2
from flask import Flask, render_template
from flask_socketio import SocketIO, emit

# Add project root to sys.path to allow absolute imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from src.radar import config
except ImportError:
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

# Pre-compute RdBu colormap lookup table once as a constant (BGR format for OpenCV)
TRANSITION_MID = 128
COLORMAP_BGR = np.zeros((256, 3), dtype=np.uint8)
for i in range(256):
    if i < TRANSITION_MID:
        ratio = i / TRANSITION_MID
        red = int(0 + 255 * ratio)
        green = int(0 + 255 * ratio)
        blue = int(139 + (255 - 139) * ratio)
    else:
        ratio = (i - TRANSITION_MID) / (255 - TRANSITION_MID)
        red = int(255 - (255 - 139) * ratio)
        green = int(255 * (1 - ratio))
        blue = int(255 * (1 - ratio))
    # BGR for OpenCV
    COLORMAP_BGR[i] = [blue, green, red]

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    logger=False,
    engineio_logger=False,
)

def array_to_raw_image(data_array):
    """Optimized conversion of 64x512 array to 512x512 BGR image data"""
    # Normalize to 0-255 range using OpenCV (highly optimized)
    normalized = cv2.normalize(data_array, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)

    # Resize to 512x512 (Nearest neighbor is fastest and matches previous behavior)
    # Input is 64x512 (H, W)
    scaled = cv2.resize(normalized, (512, 512), interpolation=cv2.INTER_NEAREST)
    
    # Rotate 90 CCW to match target orientation
    rotated = cv2.rotate(scaled, cv2.ROTATE_90_COUNTERCLOCKWISE)

    # Apply colormap using optimized numpy indexing
    bgr_image = COLORMAP_BGR[rotated]

    return bgr_image

def encode_image_data(bgr_array):
    """Encode BGR array as base64 JPEG data (much smaller and faster than BMP)"""
    # Quality 80-90 is usually plenty and much smaller
    success, buffer = cv2.imencode('.jpg', bgr_array, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not success:
        return ""
    return base64.b64encode(buffer).decode("ascii")

def extract_detections(cfar_array, angles_array, rdm_array=None):
    """Vectorized extraction of detection information"""
    # Find detection positions
    detection_indices = np.where(cfar_array > 0)
    doppler_indices = detection_indices[0]
    range_indices = detection_indices[1]
    
    if len(doppler_indices) == 0:
        return []

    # Get values at points
    angles = angles_array[doppler_indices, range_indices]
    
    # Physics constants from config
    SLOW_TIME = config.SLOW_TIME
    VELOCITY_RES = config.VELOCITY_RES
    
    # Vectorized calculations
    doppler_offsets = doppler_indices - SLOW_TIME // 2
    velocities = doppler_offsets * VELOCITY_RES
    
    magnitudes = rdm_array[doppler_indices, range_indices] if rdm_array is not None else np.zeros_like(velocities)
    
    # Pixel mapping (matching rot90 k=1 CCW)
    # new_row = 511 - old_col, new_col = old_row
    # In JS: x is col, y is row
    pixel_xs = doppler_indices * 8
    pixel_ys = 511 - range_indices
    
    # Build list of dicts (already pre-computed vectorized)
    return [
        {
            "x": int(px),
            "y": int(py),
            "doppler_idx": int(di),
            "range_idx": int(ri),
            "angle": float(a) if a != 0 else None,
            "velocity": float(v),
            "magnitude": float(m),
        }
        for px, py, di, ri, a, v, m in zip(pixel_xs, pixel_ys, doppler_indices, range_indices, angles, velocities, magnitudes)
    ]

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
    """Process array data with optimized pipelines"""
    try:
        start_time = time.time()

        # Convert RDM array data
        array_data = np.frombuffer(data["array"], dtype=np.float32)

        if array_data.size == 64 * 512:
            array_data = array_data.reshape(64, 512)
        else:
            return

        # Process detections and angles if available
        detections = []
        if data.get("angles") is not None and data.get("cfar") is not None:
            try:
                angles_array = np.frombuffer(data["angles"], dtype=np.float32).reshape(64, 512)
                cfar_array = np.frombuffer(data["cfar"], dtype=np.float32).reshape(64, 512)
                detections = extract_detections(cfar_array, angles_array, array_data)
            except Exception as angle_error:
                print(f"Error processing angles: {angle_error}")

        # Convert to image (Optimized with CV2 and JPEG)
        bgr_image = array_to_raw_image(array_data)
        image_data = encode_image_data(bgr_image)

        # Send to all clients
        emit(
            "radar_plot",
            {
                "image": image_data,
                "detections": detections,
                "mime": "image/jpeg"
            },
            broadcast=True,
        )

        # Performance logging
        process_time = (time.time() - start_time) * 1000
        if process_time > 1: # Log any significant processing
            # print(f"Frame processed in {process_time:.1f}ms (Detections: {len(detections)})")
            pass

    except Exception as e:
        print(f"Error processing array: {e}")

if __name__ == "__main__":
    print("Starting Optimized Radar Plotter on port 5001")
    socketio.run(app, host="0.0.0.0", port=5001, debug=False)
