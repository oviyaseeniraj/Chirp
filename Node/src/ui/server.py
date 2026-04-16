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
def overlay_confirmed_tracks(bgr_image, confirmed_tracks_map, confirmed_tracks_angles):
    """
    Overlay confirmed tracks on the BGR image with distinct coloring (Bright Blue).
    
    Args:
        bgr_image: Base BGR image (512x512)
        confirmed_tracks_map: 64x512 numpy array where non-zero values are track IDs
        confirmed_tracks_angles: 64x512 numpy array containing angles
    
    Returns:
        BGR image with overlaid confirmed tracks
    """
    # Create a copy to avoid modifying original
    overlay_image = bgr_image.copy()
    
    if confirmed_tracks_map is None:
        return overlay_image

    # Distinct color for confirmed tracks: Bright Blue in BGR
    TRACK_COLOR = (125, 0, 0)  # BGR format: Bright Blue (high B, medium G, low R)
    TRACK_RADIUS = 20
    TRACK_THICKNESS = 2
    TEXT_COLOR = (255, 200, 100)  # Slightly lighter blue for text
    
    # Find all coordinates where a track exists (value > 0)
    doppler_indices, range_indices = np.where(confirmed_tracks_map > 0)
    
    for d, r in zip(doppler_indices, range_indices):
        track_id = int(confirmed_tracks_map[d, r])
        
        # Convert from RDM space to image pixel space
        # Image is 512x512 after rotation
        # doppler_bin maps to x-axis (0-64 -> 0-512)
        # range_bin maps to y-axis (0-512 -> 512-0, inverted)
        pixel_x = int((d / 64.0) * 512)
        pixel_y = int(512 - (r / 512.0) * 512)
        
        # Clamp to image bounds
        pixel_x = np.clip(pixel_x, 0, 511)
        pixel_y = np.clip(pixel_y, 0, 511)
        
        # Draw filled circle for track position
        cv2.circle(overlay_image, (pixel_x, pixel_y), TRACK_RADIUS, TRACK_COLOR, -1)
        
        # Draw circle outline
        cv2.circle(overlay_image, (pixel_x, pixel_y), TRACK_RADIUS, TEXT_COLOR, TRACK_THICKNESS)
        
        # Draw track ID label
        cv2.putText(overlay_image, f"T{track_id}", (pixel_x + 10, pixel_y - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, TEXT_COLOR, 1)
        
        # Optional: Draw angle indicator if available
        if confirmed_tracks_angles is not None:
            angle = float(confirmed_tracks_angles[d, r])
            if angle != 0: # Assuming 0 might mean no angle data
                # Draw a line from center point in direction of angle
                angle_rad = np.radians(angle)
                line_length = 20
                end_x = int(pixel_x + line_length * np.cos(angle_rad))
                end_y = int(pixel_y - line_length * np.sin(angle_rad))
                cv2.line(overlay_image, (pixel_x, pixel_y), (end_x, end_y), TEXT_COLOR, 2)
    
    return overlay_image


def array_to_raw_image_with_tracks(data_array, confirmed_tracks_map=None, confirmed_tracks_angles=None):
    """
    Complete pipeline: Convert 64x512 array to 512x512 BGR image with confirmed tracks overlaid.
    
    Args:
        data_array: 64x512 RDM power array
        confirmed_tracks_map: Dict mapping track_id to [range_bin, doppler_bin]
        confirmed_tracks_angles: Dict mapping track_id to angle_value
    
    Returns:
        512x512 BGR image with RDM data and confirmed tracks
    """
    # Original processing
    normalized = cv2.normalize(data_array, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
    scaled = cv2.resize(normalized, (512, 512), interpolation=cv2.INTER_NEAREST)
    rotated = cv2.rotate(scaled, cv2.ROTATE_90_COUNTERCLOCKWISE)
    bgr_image = COLORMAP_BGR[rotated]
    
    # Overlay confirmed tracks if provided
    if confirmed_tracks_map is not None and len(confirmed_tracks_map) > 0:
        #pass
        bgr_image = overlay_confirmed_tracks(bgr_image, confirmed_tracks_map, confirmed_tracks_angles)
    
    return bgr_image


#UNUSED    
def process_frame(data):
    """CPU-bound processing logic separated from the event loop"""
    start_time = time.time()
    
    print("bruh")

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
            threshold = np.mean(array_data) + 2 * np.std(array_data)
            cfar_detections = (array_data > threshold).astype(np.uint8)
            detections = extract_detections(cfar_detections, angles_array, array_data)
        except Exception:
            pass


    
    # 3. Handle image with confirmed tracks overlay
    confirmed_tracks_map = np.frombuffer(data["confirmed_tracks_rd"], dtype=np.float32).reshape(64, 512)
    print(confirmed_tracks_map)
    
    confirmed_tracks_angles = np.frombuffer(data["confirmed_tracks_angles"], dtype=np.float32).reshape(64, 512)
    
    
    bgr_image = array_to_raw_image_with_tracks(
        array_data,
        confirmed_tracks_map,
        confirmed_tracks_angles
    )
    image_data = encode_image_data(bgr_image)

    print("bruh2")

    # 4. Convert confirmed tracks to pixel coordinates for frontend
    confirmed_tracks = []
    """try:
        for track_id, rd_data in confirmed_tracks_map.items():
            # Safely extract in case the producer sends more than just [range, doppler]
            if len(rd_data) >= 2:
                range_bin = rd_data[0]
                doppler_bin = rd_data[1]
                
                pixel_x = int((doppler_bin / 64.0) * 512)
                pixel_y = int(512 - (range_bin / 512.0) * 512)
                pixel_x = np.clip(pixel_x, 0, 511)
                pixel_y = np.clip(pixel_y, 0, 511)
                
                # Ensure track_id type matches between maps (JSON parsing usually makes keys strings)
                angle = confirmed_tracks_angles.get(str(track_id))
                if angle is None:
                    angle = confirmed_tracks_angles.get(int(track_id))
                
                confirmed_tracks.append({
                    "track_id": int(track_id),
                    "x": pixel_x,
                    "y": pixel_y,
                    "range_bin": int(range_bin),
                    "doppler_bin": int(doppler_bin),
                    "angle": float(angle) if angle is not None else None
                })
    except Exception as e:
        print(f"DEBUG: Error parsing confirmed tracks data: {e}")
    """
        
    proc_time = (time.time() - start_time) * 1000
    
    payload = {
        "image": image_data,
        "detections": detections,
        "confirmed_tracks": confirmed_tracks,
        "cluster_count": data.get("cluster_count", 0),
        "clusters": data.get("clusters", []),
        "mime": "image/jpeg"
    }

    #print("BRH ==============")
    #print(confirmed_tracks)


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
            #confirmed_count = 0
            confirmed_count = len(payload.get("confirmed_tracks", []))
            print(f"Frame {stats.frame_count} | Arrival: {arrival_delta:.1f}ms | Process: {proc_time:.1f}ms | Detections: {len(payload['detections'])} | Confirmed Tracks: {confirmed_count}")
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
        max_velocity=config.MAX_VELOCITY,
        max_range=config.MAX_RANGE,
        range_res=config.RANGE_RES,
        velocity_res=config.DOPPLER_RES,
        slow_time=config.SLOW_TIME,
        fast_time=config.FAST_TIME
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
