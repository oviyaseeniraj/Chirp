# Chirp — mmWave Radar Network

Multi-node mmWave radar system with MQTT-coordinated hardware triggering, closed-form autocalibration, and a real-time bird's-eye fusion dashboard.

**Hardware per radar node:** Jetson Orin Nano + TI AWR2243 + DCA1000EVM  
**Server / fusion center:** Jetson Xavier  
**Operator machine:** any laptop on the same network

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [One-Time Setup](#2-one-time-setup)
   - [Time Synchronization (all Jetsons)](#21-time-synchronization-all-jetsons)
   - [Xavier — MQTT Broker](#22-xavier--mqtt-broker)
   - [Xavier — Fusion-Center Python env](#23-xavier--fusion-center-python-env)
   - [Each Radar Node (Orin) — Python env & credentials](#24-each-radar-node-orin--python-env--credentials)
   - [Laptop — credentials](#25-laptop--credentials)
3. [Per-Session Startup Order](#3-per-session-startup-order)
4. [Single-Node Testing](#4-single-node-testing)
5. [Multi-Node Synchronized Capture](#5-multi-node-synchronized-capture)
6. [Autocalibration + Bird's-Eye Dashboard](#6-autocalibration--birds-eye-dashboard)
7. [Modifying Radar Parameters](#7-modifying-radar-parameters)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Jetson Xavier (server)                │
│   Mosquitto MQTT broker  ·  server_controller.py        │
│   dashboard.py  →  http://<xavier-ip>:5002              │
└────────────────────────┬────────────────────────────────┘
                         │ MQTT (port 1883)
          ┌──────────────┼──────────────┐
          │              │              │
   ┌──────▼──────┐ ┌─────▼──────┐ ┌───▼────────┐
   │  Orin Node 1│ │ Orin Node 2│ │ Orin Node N│
   │ AWR2243     │ │ AWR2243    │ │ AWR2243    │
   │ DCA1000     │ │ DCA1000    │ │ DCA1000    │
   └─────────────┘ └────────────┘ └────────────┘
                         │
                   ┌─────▼──────┐
                   │   Laptop   │
                   │ trigger CLI│
                   └────────────┘
```

Each radar node runs two long-lived services:
- **`mqtt_trigger_client.py`** — MQTT client that receives synchronized start commands and fires the hardware GPIO trigger at an absolute epoch
- **`main.py`** — DAQ → signal processing pipeline; also publishes live cluster frames to the dashboard and calibration data to the server

---

## 2. One-Time Setup

> Do this once when first bringing up a machine. Skip sections for machines already configured.

### 2.1 Time Synchronization (all Jetsons)

All Jetsons must be clock-synchronized before multi-node captures are meaningful. One Xavier or Orin acts as the NTP master; the rest are slaves.

```bash
# On every Jetson — copy and run the setup script
cd Chirp/Time-Synchronization
sudo ./CHRONY_SETUP.sh
# Select: 1 = Master (Xavier), 2 or 3 = Slave (each Orin)
# When prompted on slaves, enter the Master's IP address

# After 30 s, verify on each slave
chronyc sources -v        # look for * next to master IP
chronyc tracking          # "System time" offset should be < 1 ms
```

### 2.2 Xavier — MQTT Broker

```bash
# 1. Install Docker (Ubuntu)
#    https://docs.docker.com/engine/install/ubuntu/

# 2. Set credentials
cd Chirp/Fusion-Center/MQTT-Broker
cp .env.example .env
# Edit .env — set MQTT_HOST to Xavier's LAN IP, and set strong passwords for
# MQTT_LAPTOP_PASS, MQTT_SERVER_PASS, and MQTT_RADAR_PASSWORD

# 3. Build the Mosquitto password file from .env
chmod +x set_mqttbroker_passwords.sh start_broker.sh clear_retained.sh
sudo ./set_mqttbroker_passwords.sh

# 4. Start the broker (detached Docker container — survives terminal close)
sudo ./start_broker.sh

# 5. Verify
docker compose -f docker-compose.yaml ps
docker compose -f docker-compose.yaml logs --tail=20
```

### 2.3 Xavier — Fusion-Center Python env

```bash
cd Chirp/Fusion-Center

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2.4 Each Radar Node (Orin) — Python env & credentials

Do this once on **each Orin**:

```bash
cd Chirp/Node

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set per-node credentials and identity
cp .env.example .env
# Edit .env — set the following for this specific node:
#   MQTT_HOST        = Xavier's LAN IP
#   NODE_ID          = unique name for this node, e.g. node1
#   GROUP_ID         = default  (or a custom group name)
#   MQTT_USERNAME    = same value as NODE_ID
#   MQTT_PASSWORD    = value of MQTT_RADAR_PASSWORD from the broker .env
#   MQTT_CLIENT_ID   = radar-<NODE_ID>
```

So the MQTT username for each node **must exactly match its `NODE_ID`** — this is how the broker ACL enforces that a node can only publish to its own topics.

To make env vars available automatically on every new terminal session on the Orin:

```bash
sudo vim ~/.bashrc
# Add to the very bottom:
set -a
source /home/chirp/Chirp/Node/.env
set +a
```

Then reload:

```bash
source ~/.bashrc
```

Build the hardware trigger binary (one-time, per node):

```bash
cd Chirp/Node/src/hardware_trigger_mqtt
make
```

### 2.5 Laptop — credentials

```bash
cd Chirp/Fusion-Center/MQTT-Broker
# If .env doesn't exist here yet on the laptop, create a minimal one:
#   MQTT_HOST=<xavier-ip>
#   MQTT_LAPTOP_PASS=<value of MQTT_LAPTOP_PASS from broker .env>
#   DASHBOARD_PORT=5002

# Install paho-mqtt for the laptop trigger client
pip3 install paho-mqtt
```

---

## 3. Per-Session Startup Order

Start services in this order each time. Steps 1–2 run on Xavier; steps 3–4 run on each Orin; step 5 is the operator laptop.

```
Xavier  [1]  sudo ./start_broker.sh            ← MQTT broker (Docker, background)
Xavier  [2]  ./start_server_controller.sh      ← coordinator (keep alive in tmux)
Xavier  [3]  python3 dashboard.py              ← bird's-eye dashboard on :5002 (keep alive in tmux)

Each Orin  [4]  sudo -E .venv/bin/python3 src/hardware_trigger_mqtt/mqtt_trigger_client.py
Each Orin  [5]  python3 -m src.main

Laptop  [6]  python3 Fusion-Center/Laptop/laptop_trigger_client.py --group-id default
```

> **tmux tip:** run each long-lived service in its own pane so you can detach and reconnect.  
> `tmux new -s broker`, `tmux new -s server`, etc.

---

## 4. Single-Node Testing

Test the radar pipeline on one Orin without any MQTT coordination.

### Hardware initialization

```bash
# From Chirp/Node/scripts/
cd Chirp/Node/scripts

# Start the AWR2243 and DCA1000 (run as root)
sudo bash start_radar.sh

# If the FPGA/board is in a bad state, reset first
sudo bash reset_radar.sh
sudo bash start_radar.sh
```

### Run the pipeline

```bash
cd Chirp/Node
source .venv/bin/activate
```

| Script | Description | Usage |
| :--- | :--- | :--- |
| `run_tests.sh` | Interactive test runner — live tests, data capture, and MATLAB conversion | `sudo bash test/run_tests.sh` |
| `capture_data.py` | Capture raw ADC + processed RDM frames; convert to `.mat` | `python3 test/capture_data.py --capture --frames 100 --output data` |
| `full_integration_test.py` | Full pipeline (DAQ → Processing → Visualizer) on live data | `python3 test/full_integration_test.py` |
| `playback_test.py` | Full pipeline on previously recorded data | `python3 test/playback_test.py --input-dir data/raw --loop` |

```bash
# Capture 100 frames and save to data/
python3 test/capture_data.py --capture --frames 100 --output data

# Convert raw capture to MATLAB format
python3 test/capture_data.py --convert --input-dir data/raw --output-file data.mat --type raw

# Live pipeline + visualizer (opens browser on port 5001)
python3 test/full_integration_test.py

# Replay a previous capture
python3 test/playback_test.py --input-dir data/raw --loop
```

The `data/` subdirectory is the default location for captured frames and the source for playback.

---

## 5. Multi-Node Synchronized Capture

With all services running (Section 3), trigger a synchronized capture across all online nodes:

```bash
# On the laptop — from Chirp/Fusion-Center/Laptop/
source .env  # or export MQTT_HOST and MQTT_LAPTOP_PASS manually

# Trigger a capture (all active nodes in group "default")
./start_laptop_trigger.sh --group-id default

# Or directly:
python3 laptop_trigger_client.py --group-id default

# With a custom delay
python3 laptop_trigger_client.py --group-id default --requested-delay-ms 3000

# Print full JSON result
python3 laptop_trigger_client.py --group-id default --print-json
```

What happens:
1. Laptop publishes a start request → server selects all online nodes in the group
2. Server picks a `startEpochMs` ~5 s in the future and publishes `capture/start`
3. Each node's `mqtt_trigger_client.py` arms the GPIO trigger; each ACKs back to the server
4. At `startEpochMs` all nodes fire simultaneously (synchronized to Chrony clock)
5. Server collects ACKs and publishes a summary result; laptop prints it

---

## 6. Autocalibration + Bird's-Eye Dashboard

Autocalibration solves for the spatial position and orientation of every radar node relative to each other using a live single-target walk.

### Start the dashboard (Xavier)

```bash
cd Chirp/Fusion-Center
source .venv/bin/activate

export MQTT_HOST=127.0.0.1
export MQTT_SERVER_PASS=<server-password>
python3 dashboard.py
# Dashboard available at http://<xavier-ip>:5002
```

### Run autocalibration (laptop)

Walk a single person slowly across the radar field of view, then:

```bash
python3 laptop_trigger_client.py \
  --group-id default \
  --calibration \
  --calibration-frames 50
```

What happens end-to-end:
1. Laptop sends start request with `captureConfig: {calibration: true, calibrationFrames: 50}`
2. Server creates a `CalibrationSession`, publishes `capture/start` to all nodes
3. On each node — in parallel:
   - `mqtt_trigger_client.py` fires the GPIO trigger at `startEpochMs`
   - The pipeline's `CalibPublisher` process collects 50 frames of centroid data and streams them to `chirp/v1/group/default/calibration/frame/<nodeId>`
4. Each node publishes a done signal when its 50 frames are sent
5. Server collects from all nodes, runs the closed-form spatial calibration solver, and publishes the result (rotation + translation per node pair) to `chirp/v1/group/default/calibration/result`
6. **Browser opens automatically** at `http://<xavier-ip>:5002` — shows nodes' live detections projected into the shared global coordinate frame
7. Laptop terminal prints the calibration result (θ in degrees, P in metres)

**Calibration result** is retained on the broker — the dashboard always loads the latest result on startup, so you only need to calibrate once per session (or when nodes are physically moved).

Optional flags:

```bash
--calibration-frames 100      # collect more frames for higher accuracy
--calibration-timeout-ms 180000  # wait up to 3 min for result
--no-browser                  # suppress auto browser open
--dashboard-port 5002         # if dashboard runs on a non-default port
```

---

## 7. Modifying Radar Parameters

Radar parameters (max range, Doppler resolution, chirp config, etc.) are set in:

```
Chirp/Node/setup_radar/mmwaveconfig.txt
```

Key parameters map to TI mmWaveLink C structs (`rlProfileCfg_t`, `rlChirpCfg_t`, etc.).  
Full field definitions: [TI mmWaveLink API docs](https://astroa.net/fmcw-RADAR/mmwave_sdk/packages/ti/control/mmwavelink/docs/doxygen/html/annotated.html)

After editing `mmwaveconfig.txt`, re-run `start_radar.sh` to push the new config to the AWR2243.

---

## 8. Troubleshooting

### Broker refuses connections
- Confirm `./set_mqttbroker_passwords.sh` was run after editing `.env`
- Confirm `MQTT_USERNAME` on each node matches a username registered in the broker password file
- Confirm `MQTT_HOST` is the Xavier's LAN IP, not `127.0.0.1`, when connecting from remote machines

### Node not appearing in server's active node list
- Ensure `mqtt_trigger_client.py` is running on the node (`status=online` presence published)
- Ensure `NODE_ID` and `GROUP_ID` in the node's `.env` match what the laptop is requesting
- Presence messages expire after 6 s — confirm the heartbeat thread is alive

### `start_radar.sh` fails at FPGA config step
```bash
sudo bash reset_radar.sh
sudo bash start_radar.sh
```

### Trigger worker can't access GPIO
- `mqtt_trigger_client.py` must be run with `sudo -E` so the `trigger_worker` C binary inherits root permissions for GPIO access
- The `-E` flag preserves the environment variables from `.env`

### Calibration result never arrives
- Confirm all nodes have `CalibPublisher` process running (part of `python3 -m src.main`)
- Check that the node's MQTT user has `write` permission on `chirp/v1/group/+/calibration/frame/<nodeId>` (set by the ACL `pattern write` rule)
- Increase `--calibration-timeout-ms` if nodes are slow to process frames

### Dashboard shows "Uncalibrated"
- A calibration has not been run yet this session, **or** the retained result on the broker is stale
- Run `--calibration` from the laptop to produce a fresh result
- Broker retains the last result — it will reload automatically when the dashboard restarts

### Time sync verification
```bash
# On any slave Orin
chronyc tracking           # "System time" offset should be < 1 ms
chronyc sources -v         # * marks the active source
```
