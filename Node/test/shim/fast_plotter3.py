import base64
import logging
import struct
import time

import numpy as np
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit

# Disable all logging
logging.getLogger("werkzeug").disabled = True
logging.getLogger("socketio").disabled = True
logging.getLogger("engineio").disabled = True

app = Flask(__name__)
app.config["SECRET_KEY"] = "fast-plotter3"

# RdBu colormap transition points (0-255)
TRANSITION_MID = 128  # Middle point (white)

# Pre-compute RdBu colormap lookup table once as a constant
COLORMAP = np.zeros((256, 3), dtype=np.uint8)
for i in range(256):
    if i < TRANSITION_MID:
        # Dark blue to white (first half)
        ratio = i / TRANSITION_MID
        # Start from dark blue (0, 0, 139) and transition to white (255, 255, 255)
        red = int(0 + 255 * ratio)
        green = int(0 + 255 * ratio)
        blue = int(139 + (255 - 139) * ratio)
        COLORMAP[i] = [red, green, blue]
    else:
        # White to dark red (second half)
        ratio = (i - TRANSITION_MID) / (255 - TRANSITION_MID)
        # Start from white (255, 255, 255) and transition to dark red (139, 0, 0)
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
    """Convert 64x256 array to 512x512 RGB image data (much faster than matplotlib)"""
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

    # Create a simple bitmap header (Windows BMP format is simpler than PNG)
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


def extract_detections(cfar_array, angles_array):
    """Extract detection information from CFAR and angles arrays"""
    detections = []

    # Find detection positions
    detection_indices = np.where(cfar_array > 0)

    for i in range(len(detection_indices[0])):
        doppler_idx = detection_indices[0][i]
        range_idx = detection_indices[1][i]

        # Get angle for this detection (0 means no angle estimate)
        angle_deg = angles_array[doppler_idx, range_idx]

        # Convert indices to pixel coordinates (accounting for scaling and rotation)
        # Original: (64, 256) -> Scaled: (512, 512) -> Rotated 90 degrees CCW
        # After np.rot90(k=1): rows become columns (rotated left)
        # Original coordinates: doppler_idx (row), range_idx (col)
        # After scaling: doppler_idx * 8, range_idx * 2
        # After rot90(k=1): new_x = old_y, new_y = width - old_x - 1

        scaled_x = int(range_idx * 2)  # column scaling
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
            }
        )

    return detections


HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Radar Plot with Angles</title>
    <script src="https://cdn.socket.io/4.0.0/socket.io.min.js"></script>
    <style>
        body {
            margin: 0;
            padding: 0;
            background-color: black;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            font-family: 'Courier New', monospace;
        }
        #container {
            position: relative;
            display: inline-block;
        }
        #plot-canvas {
            border: 1px solid #333;
        }
        #overlay-canvas {
            position: absolute;
            top: 0;
            left: 0;
            pointer-events: none;
        }
        #fps-display {
            position: fixed;
            top: 10px;
            left: 10px;
            color: white;
            font-size: 14px;
            background-color: rgba(0, 0, 0, 0.8);
            padding: 8px 12px;
            border-radius: 4px;
            border: 1px solid #555;
        }
        #legend {
            position: fixed;
            top: 10px;
            right: 10px;
            color: white;
            font-size: 12px;
            background-color: rgba(0, 0, 0, 0.8);
            padding: 8px 12px;
            border-radius: 4px;
            border: 1px solid #555;
            line-height: 1.4;
        }
    </style>
</head>
<body>
    <div id="fps-display">FPS: 0 | Latency: 0ms | Detections: 0</div>
    <div id="legend">
        <div style="color: #ff6666;">● Detection Point</div>
        <div style="color: #ffff66;">Angle (degrees)</div>
    </div>

    <div id="container">
        <canvas id="plot-canvas" width="512" height="512"></canvas>
        <canvas id="overlay-canvas" width="512" height="512"></canvas>
    </div>

    <script>
        const socket = io();
        let frameCount = 0;
        let lastTime = Date.now();
        let lastFrameTime = Date.now();
        let latency = 0;
        let detectionCount = 0;

        const plotCanvas = document.getElementById('plot-canvas');
        const overlayCanvas = document.getElementById('overlay-canvas');
        const plotCtx = plotCanvas.getContext('2d');
        const overlayCtx = overlayCanvas.getContext('2d');

        // Update FPS display
        setInterval(() => {
            const now = Date.now();
            const delta = (now - lastTime) / 1000;
            const fps = (frameCount / delta).toFixed(1);
            document.getElementById('fps-display').textContent =
                `FPS: ${fps} | Latency: ${latency}ms | Detections: ${detectionCount}`;
            frameCount = 0;
            lastTime = now;
        }, 1000);

        function drawDetections(detections) {
            // Clear overlay
            overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

            detectionCount = detections.length;

            detections.forEach(detection => {
                const { x, y, angle } = detection;

                // Draw detection marker (red circle)
                overlayCtx.strokeStyle = '#ff6666';
                overlayCtx.fillStyle = '#ff6666';
                overlayCtx.lineWidth = 2;
                overlayCtx.beginPath();
                overlayCtx.arc(x, y, 4, 0, 2 * Math.PI);
                overlayCtx.stroke();

                // Draw cross inside circle
                overlayCtx.beginPath();
                overlayCtx.moveTo(x - 3, y);
                overlayCtx.lineTo(x + 3, y);
                overlayCtx.moveTo(x, y - 3);
                overlayCtx.lineTo(x, y + 3);
                overlayCtx.stroke();

                // Draw angle text if available
                if (angle !== null && angle !== undefined) {
                    overlayCtx.fillStyle = '#ffff66';
                    overlayCtx.font = '11px Courier New';
                    overlayCtx.textAlign = 'left';
                    overlayCtx.textBaseline = 'top';

                    // Position text to the right and slightly below the detection
                    const textX = x + 8;
                    const textY = y + 2;

                    // Add black outline for better visibility
                    overlayCtx.strokeStyle = '#000000';
                    overlayCtx.lineWidth = 3;
                    overlayCtx.strokeText(angle.toFixed(1) + '°', textX, textY);

                    overlayCtx.fillText(angle.toFixed(1) + '°', textX, textY);
                }
            });
        }

        socket.on('radar_plot', function(data) {
            const now = Date.now();
            latency = now - lastFrameTime;
            lastFrameTime = now;

            // Draw background RDM image
            const img = new Image();
            img.onload = function() {
                plotCtx.clearRect(0, 0, plotCanvas.width, plotCanvas.height);
                plotCtx.drawImage(img, 0, 0, plotCanvas.width, plotCanvas.height);

                // Draw detection overlays
                if (data.detections) {
                    drawDetections(data.detections);
                }

                frameCount++;
            };
            img.src = 'data:image/bmp;base64,' + data.image;
        });

        // Handle connection events
        socket.on('connect', function() {
            console.log('Connected to server');
        });

        socket.on('disconnect', function() {
            console.log('Disconnected from server');
        });
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@socketio.on("send_frame")
def handle_array(data):
    """Process array data with angle overlay support"""
    try:
        start_time = time.time()

        # Convert RDM array data
        array_data = np.frombuffer(data["array"], dtype=np.float32)

        if array_data.size == 64 * 256:
            array_data = array_data.reshape(64, 256)

        if array_data.shape != (64, 256):
            print(f"Invalid array shape: {array_data.shape}")
            return

        # Process detections and angles if available
        detections = []
        if "angles" in data and "cfar" in data:
            try:
                angles_array = np.array(data["angles"], dtype=np.float32)
                cfar_array = np.array(data["cfar"], dtype=np.float32)

                if angles_array.shape == (64, 256) and cfar_array.shape == (64, 256):
                    # Use actual CFAR detections
                    detections = extract_detections(cfar_array, angles_array)
                    print(f"Found {len(detections)} detections with angles")
            except Exception as angle_error:
                print(f"Error processing angles/CFAR: {angle_error}")
        elif "angles" in data:
            try:
                angles_array = np.array(data["angles"], dtype=np.float32)
                if angles_array.shape == (64, 256):
                    # Fallback: create CFAR-like detection map from RDM data
                    threshold = np.mean(array_data) + 2 * np.std(array_data)
                    cfar_detections = (array_data > threshold).astype(np.uint8)
                    detections = extract_detections(cfar_detections, angles_array)
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
