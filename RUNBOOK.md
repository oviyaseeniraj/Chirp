# Chirp Runbook

Step-by-step commands to bring up the full system. See `README.md` for architecture and explanations.

---

## Legend

| Symbol | Machine |
| :--- | :--- |
| `[XAVIER]` | Jetson Xavier (fusion center / server) |
| `[ORIN]` | Each Jetson Orin Nano (radar node) — repeat on every node |
| `[LAPTOP]` | Operator laptop |

---

## Part 0 — First-Time Setup

> Run once per machine. Skip if already done.

### [XAVIER] — MQTT broker credentials

```bash
cd Chirp/Fusion-Center/MQTT-Broker
cp .env.example .env
# Edit .env: set MQTT_HOST to Xavier's LAN IP, set passwords for
#   MQTT_LAPTOP_PASS, MQTT_SERVER_PASS, MQTT_RADAR_PASSWORD

chmod +x set_mqttbroker_passwords.sh start_broker.sh clear_retained.sh
sudo ./set_mqttbroker_passwords.sh
```

### [XAVIER] — Fusion-Center Python environment

```bash
cd Chirp/Fusion-Center
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### [ORIN] — Node Python environment & credentials

```bash
cd Chirp/Node
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env for this specific node:
#   MQTT_HOST      = Xavier's LAN IP
#   NODE_ID        = unique node name, e.g. node1
#   GROUP_ID       = default
#   MQTT_USERNAME  = same as NODE_ID
#   MQTT_PASSWORD  = value of MQTT_RADAR_PASSWORD from broker .env
#   MQTT_CLIENT_ID = radar-<NODE_ID>
```

Auto-source `.env` on every terminal open:

```bash
sudo vim ~/.bashrc
# Add to the bottom:
#   set -a
#   source /home/chirp/Chirp/Node/.env
#   set +a
source ~/.bashrc
```

Build the hardware trigger binary:

```bash
cd Chirp/Node/src/hardware_trigger_mqtt
make
```

### [ORIN] — Time synchronization

```bash
cd Chirp/Time-Synchronization
sudo ./CHRONY_SETUP.sh
# Xavier = option 1 (Master), each Orin = option 2 or 3 (Slave)
# Enter Xavier's IP when prompted on slaves

sleep 30
chronyc sources -v    # * should appear next to Xavier's IP
chronyc tracking      # System time offset should be < 1 ms
```

### [LAPTOP] — Credentials

```bash
# Create a local .env or export these before running the trigger client:
export MQTT_HOST=<xavier-ip>
export MQTT_LAPTOP_PASS=<value of MQTT_LAPTOP_PASS from broker .env>
export DASHBOARD_PORT=5002
```

---

## Part 1 — Per-Session Startup

Run in this order every time. Use `tmux` to keep services alive.

### Step 1 — [XAVIER] Start MQTT broker

```bash
cd Chirp/Fusion-Center/MQTT-Broker
sudo ./start_broker.sh

# Verify
docker compose -f docker-compose.yaml ps
```

### Step 2 — [XAVIER] Start server controller

```bash
cd Chirp/Fusion-Center
source .venv/bin/activate
./start_server_controller.sh
```

### Step 3 — [XAVIER] Start bird's-eye dashboard

```bash
cd Chirp/Fusion-Center
source .venv/bin/activate

export MQTT_HOST=127.0.0.1
export MQTT_SERVER_PASS=<server-password>
python3 dashboard.py
# Dashboard → http://<xavier-ip>:5002
```

### Step 4 — [ORIN] Initialize radar hardware

```bash
cd Chirp/Node/scripts
sudo bash start_radar.sh

# If hardware is in a bad state, reset first:
sudo bash reset_radar.sh
sudo bash start_radar.sh
```

### Step 5 — [ORIN] Start MQTT trigger client

```bash
cd Chirp/Node/src/hardware_trigger_mqtt
sudo -E /home/chirp/Chirp/Node/.venv/bin/python3 mqtt_trigger_client.py
```

> Must use `sudo -E` — the C trigger worker needs root for GPIO access, and `-E` preserves the `.env` variables.

### Step 6 — [ORIN] Start the signal processing pipeline

```bash
cd Chirp/Node
source .venv/bin/activate
python3 -m src.main
```

Repeat Steps 4–6 on every Orin before triggering from the laptop.

---

## Part 2 — Operations

### Normal synchronized capture

```bash
# [LAPTOP] — from Chirp/Fusion-Center/Laptop/
python3 laptop_trigger_client.py --group-id default
```

### Autocalibration capture

Walk a single person slowly across the radar field of view, then:

```bash
# [LAPTOP]
python3 laptop_trigger_client.py \
  --group-id default \
  --calibration \
  --calibration-frames 50
```

Browser opens automatically at `http://<xavier-ip>:5002`.  
Calibration result prints in the terminal when the server solves it.

### Single-node test (no MQTT)

```bash
# [ORIN] — interactive test runner
cd Chirp/Node
source .venv/bin/activate
sudo bash test/run_tests.sh

# Or directly:
python3 test/full_integration_test.py               # live pipeline + visualizer
python3 test/playback_test.py --input-dir data/raw  # replay recorded data
python3 test/capture_data.py --capture --frames 100 --output data  # capture frames
```

---

## Part 3 — Teardown

```bash
# [ORIN] Ctrl-C on pipeline and trigger client, then stop radar
cd Chirp/Node/scripts
sudo bash reset_radar.sh

# [XAVIER] Ctrl-C on dashboard and server controller, then stop broker
cd Chirp/Fusion-Center/MQTT-Broker
docker compose -f docker-compose.yaml down
```

---

## Quick Reference — Laptop trigger flags

| Flag | Default | Description |
| :--- | :--- | :--- |
| `--group-id` | *(required)* | Target radar group |
| `--calibration` | off | Enable autocalibration mode |
| `--calibration-frames` | `50` | Frames per node to collect |
| `--calibration-timeout-ms` | `120000` | Max wait for calibration result |
| `--requested-delay-ms` | server default | Override start delay |
| `--dashboard-port` | `5002` | Dashboard port for auto browser open |
| `--no-browser` | off | Suppress auto browser open |
| `--print-json` | off | Print full JSON result instead of summary |
| `--timeout-ms` | `12000` | Max wait for start/result ACK |
