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
    <title>Dual Fast Plotter</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        body {
            margin: 0;
            padding: 20px;
            background-color: #1a1a1a;
            font-family: monospace;
            color: #00ff00;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        h1 {
            margin-bottom: 20px;
        }
        .container {
            display: flex;
            gap: 20px;
            justify-content: center;
            align-items: flex-start;
            flex-wrap: wrap;
        }
        .plot-container {
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .plot-container h2 {
            margin: 0 0 10px 0;
            font-size: 18px;
        }
        canvas {
            border: 2px solid #00ff00;
            background-color: #000;
            image-rendering: pixelated;
        }
        #fps {
            margin-top: 20px;
            font-size: 16px;
        }
    </style>
</head>
<body>
    <h1>CPP DAQ</h1>
    <div class="container">
        <div class="plot-container">
            <h2>Python Processing</h2>
            <canvas id="plot1" width="512" height="512"></canvas>
        </div>
        <div class="plot-container">
            <h2>Cpp Processing</h2>
            <canvas id="plot2" width="512" height="512"></canvas>
        </div>
    </div>
    <div id="fps">FPS: 0 | Latency: 0ms</div>

    <script>
        const socket = io();
        const canvas1 = document.getElementById('plot1');
        const ctx1 = canvas1.getContext('2d', { alpha: false });
        const canvas2 = document.getElementById('plot2');
        const ctx2 = canvas2.getContext('2d', { alpha: false });
        const fpsDisplay = document.getElementById('fps');

        let frameCount = 0;
        let lastTime = Date.now();
        let fps = 0;
        let latency = 0;

        socket.on('fast_plot', function(data) {
            const receiveTime = Date.now();

            // Create images from base64 data
            const img1 = new Image();
            const img2 = new Image();

            img1.onload = function() {
                ctx1.drawImage(img1, 0, 0);
            };

            img2.onload = function() {
                ctx2.drawImage(img2, 0, 0);
            };

            img1.src = 'data:image/bmp;base64,' + data.image1;
            img2.src = 'data:image/bmp;base64,' + data.image2;

            // Calculate FPS
            frameCount++;
            const currentTime = Date.now();
            const elapsed = currentTime - lastTime;

            if (elapsed >= 1000) {
                fps = Math.round(frameCount * 1000 / elapsed);
                frameCount = 0;
                lastTime = currentTime;
            }

            // Calculate latency
            if (data.timestamp) {
                latency = receiveTime - data.timestamp;
            }

            fpsDisplay.textContent = `FPS: ${fps} | Latency: ${latency}ms`;
        });

        socket.on('connect', function() {
            console.log('Connected to server');
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
    """Process two array data with maximum speed"""
    try:
        start_time = time.time()

        # Convert first array to numpy array
        array_data1 = np.frombuffer(data["array_pypros"], dtype=np.uint8)
        if array_data1.size == 64 * 256:
            array_data1 = array_data1.reshape(64, 256)
        if array_data1.shape != (64, 256):
            return

        # Convert second array to numpy array
        array_data2 = np.frombuffer(data["array_cpppros"], dtype=np.float32)
        if array_data2.size == 64 * 256:
            array_data2 = array_data2.reshape(64, 256)
        if array_data2.shape != (64, 256):
            return

        # Convert both to fast image format
        rgb_image1 = array_to_raw_image(array_data1)
        image_data1 = encode_image_data(rgb_image1)

        rgb_image2 = array_to_raw_image(array_data2)
        image_data2 = encode_image_data(rgb_image2)

        # Send to all clients
        emit(
            "fast_plot",
            {
                "image1": image_data1,
                "image2": image_data2,
                "timestamp": int(time.time() * 1000),
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
