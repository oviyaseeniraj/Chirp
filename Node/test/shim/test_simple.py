import matplotlib

matplotlib.use("Agg")
import base64
import io

import matplotlib.pyplot as plt
import numpy as np
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config["SECRET_KEY"] = "plotter-key"

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
)


def plot_array(data_array):
    """Plot a 64x512 array and return as base64 image"""
    fig, ax = plt.subplots(figsize=(10, 6))

    im = ax.imshow(data_array, cmap="viridis", aspect="auto")
    ax.set_title(f"Array Plot - Shape: {data_array.shape}")
    ax.set_xlabel("Columns")
    ax.set_ylabel("Rows")
    plt.colorbar(im, ax=ax)

    # Convert to base64
    img_buffer = io.BytesIO()
    fig.savefig(img_buffer, format="png", bbox_inches="tight", dpi=80)
    img_buffer.seek(0)
    img_base64 = base64.b64encode(img_buffer.getvalue()).decode()
    img_buffer.close()
    plt.close(fig)

    return img_base64


HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Array Plotter</title>
    <script src="https://cdn.socket.io/4.0.0/socket.io.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .status { padding: 10px; margin: 10px; border: 2px solid; border-radius: 5px; }
        .connected { border-color: green; background-color: #e7f5e7; }
        .disconnected { border-color: red; background-color: #f5e7e7; }
        .plot { margin: 20px 0; text-align: center; }
        .plot img { max-width: 100%; height: auto; }
    </style>
</head>
<body>
    <h1>64x512 Array Plotter</h1>

    <div id="status" class="status disconnected">
        Status: <span id="connection-status">Connecting...</span>
    </div>

    <div id="plot-area" class="plot">
        <p>Waiting for data...</p>
    </div>

    <script>
        const socket = io();

        socket.on('connect', function() {
            document.getElementById('connection-status').textContent = 'Connected ✓';
            document.getElementById('status').className = 'status connected';
        });

        socket.on('disconnect', function() {
            document.getElementById('connection-status').textContent = 'Disconnected ✗';
            document.getElementById('status').className = 'status disconnected';
        });

        socket.on('new_plot', function(data) {
            const plotArea = document.getElementById('plot-area');
            plotArea.innerHTML = '<img src="data:image/png;base64,' + data.plot + '" alt="Array Plot">';
        });
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@socketio.on("send_array")
def handle_array(data):
    """Receive array data and plot it"""
    try:
        array_data = np.array(data["array"], dtype=float)

        # Reshape if needed
        if array_data.size == 64 * 512:
            array_data = array_data.reshape(64, 512)

        print(
            f"Received array: shape={array_data.shape}, min={array_data.min():.2f}, max={array_data.max():.2f}"
        )

        # Generate plot
        plot_base64 = plot_array(array_data)
        emit("new_plot", {"plot": plot_base64}, broadcast=True)

    except Exception as e:
        print(f"Error plotting array: {e}")


if __name__ == "__main__":
    print("Starting array plotter on http://0.0.0.0:5000")
    socketio.run(app, host="0.0.0.0", port=5000)
