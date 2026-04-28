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

From the **repo root** (the `Chirp` directory), one command creates `Fusion-Center/MQTT-Broker/.env`, sets `MQTT_HOST` to this machine’s LAN IP, replaces example passwords with random secrets, and runs `set_mqttbroker_passwords` under `sudo` (same as before, but no manual editing):

```bash
cd Chirp
chmod +x scripts/chirp_install_shell_rc.sh
./scripts/chirp_runbook_xavier_mqtt.sh
```

To customize broker users, node list, or passwords later, edit `Fusion-Center/MQTT-Broker/.env` and re-run `sudo Fusion-Center/MQTT-Broker/set_mqttbroker_passwords.sh`. Restart the broker container if it was already running.

> **Note:** `start_broker.sh` also refreshes `MQTT_HOST` in `.env` when it still looks like `X.X.X.X`, so routine broker startups stay aligned with the LAN.

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

cd ..
./scripts/chirp_runbook_orin_env.sh              # or: ./scripts/chirp_runbook_orin_env.sh node1
./scripts/chirp_install_shell_rc.sh orin "$(pwd)"
source ~/.bashrc
```

`chirp_runbook_orin_env.sh` creates `Node/.env` from `.env.example` if needed, sets **`MQTT_HOST`** (from `Fusion-Center/MQTT-Broker/.env` on the same clone, from repo-root **`.chirp_broker_ip`**, or pass **`<broker_ip>`** as the second argument), sets **`NODE_ID`** (argument or `CHIRP_NODE_ID` or short hostname), and copies **`MQTT_PASSWORD`** from **`MQTT_RADAR_PASSWORD`** in the broker `.env` when that file is present.

If this Orin does **not** have `Fusion-Center/` checked out, copy **`.chirp_broker_ip`** from the Xavier after running the Xavier MQTT step, or run:

`./scripts/chirp_runbook_orin_env.sh node1 <xavier-lan-ip>`

Edit `Node/.env` for **Supabase** and any non-default **GROUP_ID** if your deployment uses them.

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

With a **full Chirp clone** that already has `Fusion-Center/MQTT-Broker/.env` (from the Xavier, or after syncing that file from the Xavier):

```bash
cd Chirp
./scripts/chirp_runbook_laptop_env.sh
./scripts/chirp_install_shell_rc.sh laptop "$(pwd)"
source ~/.bashrc
```

That writes `Fusion-Center/Laptop/.env` and `start_laptop_trigger.sh` loads it (or the broker `.env`) automatically. If you keep only a partial tree, copy `MQTT-Broker/.env` from the Xavier and point `MQTT_HOST` / `MQTT_LAPTOP_PASS` at that file manually.

---

## Part 1 — Per-Session Startup

Run in this order every time. Use `tmux` to keep services alive.

### Step 1 — [XAVIER] Start MQTT broker

```bash
cd Chirp/Fusion-Center/MQTT-Broker
sudo ./start_broker.sh

# Verify
sudo docker compose -f docker-compose.yaml ps
```

### Step 2 — [XAVIER] Start server controller

```bash
cd Chirp/Fusion-Center
pip install -r requirements.txt
source .venv/bin/activate
./start_server_controller.sh
```

### Step 3 — [XAVIER] Start bird's-eye dashboard

```bash
cd Chirp
./scripts/chirp_runbook_xavier_dashboard.sh
# Dashboard → http://<xavier-ip>:5002
```

If the repo has no `Fusion-Center/dashboard.py`, start it however your tree provides it, using `MQTT-Broker/.env` for credentials and `MQTT_HOST=127.0.0.1` on the Xavier.

### Step 4 — [ORIN] Initialize radar hardware

```bash
cd Chirp/Node/scripts
sudo bash start_radar.sh

# If hardware is in a bad state, reset first:
sudo bash reset_radar.sh
sudo bash start_radar.sh

# if nmcli error, activate ethernet and UCSB wireless web
sudo nmtui

# if build not found
cd Chirp/Node/setup_radar
cmake -S . -B build
cmake --build build
```

### Step 5 — [ORIN] Start MQTT trigger client

```bash
cd Chirp/Node/src/hardware_trigger_mqtt
sudo -E ../../.venv/bin/python3 mqtt_trigger_client.py
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
./start_laptop_trigger.sh --group-id default
```

### Autocalibration capture

Walk a single person slowly across the radar field of view, then:

```bash
# [LAPTOP]
./start_laptop_trigger.sh \
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
sudo docker compose -f docker-compose.yaml down
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
