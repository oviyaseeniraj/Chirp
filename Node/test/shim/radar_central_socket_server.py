import socketio
import eventlet
import eventlet.wsgi
from flask import Flask
import numpy as np
import os

# Central Socket.IO server to aggregate radar node data and relay to calibration client
sio = socketio.Server(async_mode='eventlet', cors_allowed_origins='*')
app = Flask(__name__)

# Store latest centroids per node and frame (optional, for debugging)
latest_data = {}

@sio.on('send_frame')
def handle_send_frame(sid, data):
    # Broadcast to all connected calibration clients
    sio.emit('send_frame', data)
    # Optionally store for debugging
    node_id = data.get('node_id', 'unknown')
    frame_num = data.get('frame_num', -1)
    latest_data[(node_id, frame_num)] = data
    print(f"Received frame {frame_num} from {node_id} (len={len(data.get('centroids', b''))})")

@app.route('/')
def index():
    return "Radar Central Socket.IO Server is running."

if __name__ == '__main__':
    port = int(os.environ.get('RADAR_SOCKET_PORT', 5001))
    print(f"Starting central Socket.IO server on port {port}...")
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), socketio.WSGIApp(sio, app))
