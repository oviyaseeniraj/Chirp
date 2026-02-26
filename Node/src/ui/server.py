import asyncio
import base64
import logging
import time
import sys
import os
import numpy as np
import cv2
from aiohttp import web
import socketio
from jinja2 import Environment, FileSystemLoader

# Add project root to sys.path to allow absolute imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from src.radar import config
except ImportError:
    from ..radar import config

# Configuration
SHOW_RANGE_ANGLE_PLOT = True
RANGE_ANGLE_PLOT_WIDTH = 400
RANGE_ANGLE_PLOT_HEIGHT = 300

# Pre-compute RdBu colormap lookup table
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
    COLORMAP_BGR[i] = [blue, green, red]

# Async SocketIO Server
sio = socketio.AsyncServer(
    async_mode='aiohttp', 
    cors_allowed_origins='*',
    max_http_buffer_size=10000000 # 10MB to handle large radar frames
)
app = web.Application()
sio.attach(app)

@sio.event
async def connect(sid, environ):
    print(f"DEBUG: Client connected: {sid}")

@sio.event
async def disconnect(sid):
    print(f"DEBUG: Client disconnected: {sid}")

# Jinja2 setup
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'templates'))
jinja_env = Environment(loader=FileSystemLoader(template_dir))

def array_to_raw_image(data_array):
    """Optimized conversion of 64x512 array to 512x512 BGR image data"""
    # Normalize to 0-255
    normalized = cv2.normalize(data_array, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
    # Resize to 512x512
    scaled = cv2.resize(normalized, (512, 512), interpolation=cv2.INTER_NEAREST)
    # Rotate 90 CCW
    rotated = cv2.rotate(scaled, cv2.ROTATE_90_COUNTERCLOCKWISE)
    # Apply colormap
    return COLORMAP_BGR[rotated]

def encode_image_data(bgr_array):
    """Encode BGR array as base64 JPEG data"""
    success, buffer = cv2.imencode('.jpg', bgr_array, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buffer).decode("ascii") if success else ""

def extract_detections(cfar_array, angles_array, rdm_array=None):
    """Vectorized extraction of detection information"""
    detection_indices = np.where(cfar_array > 0)
    doppler_indices = detection_indices[0]
    range_indices = detection_indices[1]
    
    if len(doppler_indices) == 0:
        return []

    angles = angles_array[doppler_indices, range_indices]
    
    SLOW_TIME = config.SLOW_TIME
    VELOCITY_RES = config.VELOCITY_RES
    
    doppler_offsets = doppler_indices - SLOW_TIME // 2
    velocities = doppler_offsets * VELOCITY_RES
    
    magnitudes = rdm_array[doppler_indices, range_indices] if rdm_array is not None else np.zeros_like(velocities)
    
    pixel_xs = doppler_indices * 8
    pixel_ys = 511 - range_indices
    
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

class PerformanceStats:
    def __init__(self):
        self.last_arrival = 0
        self.frame_count = 0

stats = PerformanceStats()

def process_frame(data):
    """CPU-bound processing logic separated from the event loop"""
    start_time = time.time()
    
    # 1. Parse array
    try:
        array_data = np.frombuffer(data["array"], dtype=np.float32)
        if array_data.size == 64 * 512:
            array_data = array_data.reshape(64, 512)
        else:
            return None, 0
    except Exception:
        return None, 0

    # 2. Process detections
    detections = []
    if data.get("angles") is not None and data.get("cfar") is not None:
        try:
            angles_array = np.frombuffer(data["angles"], dtype=np.float32).reshape(64, 512)
            cfar_array = np.frombuffer(data["cfar"], dtype=np.float32).reshape(64, 512)
            detections = extract_detections(cfar_array, angles_array, array_data)
        except Exception:
            pass
    elif data.get("angles") is not None:
        try:
            angles_array = np.frombuffer(data["angles"], dtype=np.float32).reshape(64, 512)
            # Robust fallback: create CFAR-like detection map from RDM data
            threshold = np.mean(array_data) + 2 * np.std(array_data)
            cfar_detections = (array_data > threshold).astype(np.uint8)
            detections = extract_detections(cfar_detections, angles_array, array_data)
        except Exception:
            pass

    # 3. Handle image
    bgr_image = array_to_raw_image(array_data)
    image_data = encode_image_data(bgr_image)
    
    proc_time = (time.time() - start_time) * 1000
    
    payload = {
        "image": image_data,
        "detections": detections,
        "cluster_count": data.get("cluster_count", 0),
        "clusters": data.get("clusters", []),
        "mime": "image/jpeg"
    }
    return payload, proc_time

@sio.on("send_frame")
async def handle_array(sid, data):
    """Async handler for incoming radar frames"""
    now = time.time()
    arrival_delta = (now - stats.last_arrival) * 1000 if stats.last_arrival > 0 else 0
    stats.last_arrival = now
    stats.frame_count += 1

    try:
        # Offload CPU work to a thread
        payload, proc_time = await asyncio.to_thread(process_frame, data)
        
        if payload:
            await sio.emit("radar_plot", payload)
            print(f"Frame {stats.frame_count} | Arrival: {arrival_delta:.1f}ms | Process: {proc_time:.1f}ms | Detections: {len(payload['detections'])}")
        else:
            print(f"Frame {stats.frame_count} | Arrival: {arrival_delta:.1f}ms | ERROR: process_frame returned None")
    except Exception as e:
        print(f"Frame {stats.frame_count} | ERROR in handle_array: {e}")

async def index_handler(request):
    """Serve the main UI page using Jinja2"""
    print("DEBUG: index.html requested")
    template = jinja_env.get_template('index.html')
    content = template.render(
        show_range_angle_plot=SHOW_RANGE_ANGLE_PLOT,
        range_angle_plot_width=RANGE_ANGLE_PLOT_WIDTH,
        range_angle_plot_height=RANGE_ANGLE_PLOT_HEIGHT,
        max_velocity=config.MAX_VELOCITY
    )
    return web.Response(text=content, content_type='text/html')

async def status_handler(request):
    """Simple health check"""
    return web.Response(text="Server is UP", content_type='text/plain')

# Setup routes
app.router.add_get('/', index_handler)
app.router.add_get('/status', status_handler)

if __name__ == "__main__":
    print("Starting Optimized Asyncio/Aiohttp Radar Plotter on port 5001")
    # Disable access log for performance, but we can check manual prints
    web.run_app(app, host="0.0.0.0", port=5001, access_log=None)
