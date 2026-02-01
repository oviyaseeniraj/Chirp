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
app.config["SECRET_KEY"] = "fast-plotter"

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

    # Create RGB image using a simple colormap (viridis-like)
    # This is much faster than matplotlib's colormap
    rgb_array = np.zeros((512, 512, 3), dtype=np.uint8)

    # Simple colormap: blue -> green -> red
    rgb_array[:, :, 0] = scaled_array  # Red channel
    rgb_array[:, :, 1] = 255 - scaled_array  # Green channel (inverted)
    rgb_array[:, :, 2] = 128  # Blue channel (constant)

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


HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Array Plotter</title>
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
        }
    </style>
</head>
<body>
    <canvas id="plot-canvas" width="512" height="512"></canvas>

    <script>
        const socket = io();

        socket.on('fast_plot', function(data) {
            const canvas = document.getElementById('plot-canvas');
            const ctx = canvas.getContext('2d');

            const img = new Image();
            img.onload = function() {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            };
            img.src = 'data:image/bmp;base64,' + data.image;
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
    """Process array data with maximum speed"""
    try:
        start_time = time.time()

        # Convert to numpy array
        array_data = np.frombuffer(data["array"], dtype=np.uint8)

        if array_data.size == 64 * 256:
            array_data = array_data.reshape(64, 256)

        if array_data.shape != (64, 256):
            return
        # Convert to fast image format
        rgb_image = array_to_raw_image(array_data)
        image_data = encode_image_data(rgb_image)

        # Send to all clients
        emit(
            "fast_plot",
            {
                "image": image_data,
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
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
