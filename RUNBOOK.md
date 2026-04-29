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

### [XAVIER] — Fusion-Center `.env` and MQTT broker passwords

Configuration lives in a **single** file: `Fusion-Center/.env` (gitignored). Copy the template and fill in real values — especially **`MQTT_HOST`** as the Xavier’s LAN IPv4 (never leave `X.X.X.X`), Supabase keys, and the **`MQTT_*`** passwords that match how you run Mosquitto.

```bash
cd Chirp
cp Fusion-Center/.env.example Fusion-Center/.env
# Edit Fusion-Center/.env with your IP, secrets, and MQTT_LAPTOP_*, MQTT_SERVER_*, MQTT_RADAR_* values.

chmod +x scripts/chirp_install_shell_rc.sh
./scripts/chirp_runbook_xavier_mqtt.sh
```

`chirp_runbook_xavier_mqtt.sh` replaces only **placeholder** broker passwords (same strings as in `.env.example`) with random secrets when needed, runs `sudo Fusion-Center/MQTT-Broker/set_mqttbroker_passwords.sh` (which reads **`Fusion-Center/.env`** first), and writes `.chirp_radar_mqtt_password` for Orin bootstrap scripts.

To change users, node list, or passwords later, edit `Fusion-Center/.env` and re-run `sudo Fusion-Center/MQTT-Broker/set_mqttbroker_passwords.sh`. Restart the broker container if it was already running.

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

`chirp_runbook_orin_env.sh` only ensures `Node/.env` exists (copies from `Node/.env.example` once). Edit **`MQTT_HOST`** (Xavier IPv4, same as in `Fusion-Center/.env` on the server), **`NODE_ID`**, **`MQTT_USERNAME`** (usually same as `NODE_ID`), **`MQTT_PASSWORD`** (same as **`MQTT_RADAR_PASSWORD`** on the broker), **`MQTT_CLIENT_ID`** (e.g. `radar-node2`), **`GROUP_ID`**, **`CHIRP_SCHEMA_VERSION`**, and **Supabase** keys as needed.

Optional: copy **`.chirp_broker_ip`** and **`.chirp_radar_mqtt_password`** from the Xavier repo root after **`chirp_runbook_xavier_mqtt.sh`**, or run **`./scripts/chirp_bootstrap_all_orins.sh`** from a host with SSH to every Orin (see **`scripts/chirp_orin_inventory.txt`**).

#### [XAVIER] — Push `Node/.env` to all Orins over SSH (optional)

After **`Fusion-Center/.env`** exists on the Xavier and **`chirp_runbook_xavier_mqtt.sh`** has been run, with passwordless (or interactive) **SSH** to each Orin as **`chirp`**, and the same repo path on each (default **`~/Chirp`**):

```bash
cd Chirp
./scripts/chirp_bootstrap_all_orins.sh
```

Targets and **`NODE_ID`**s are listed in **`scripts/chirp_orin_inventory.txt`** (must match **`MQTT_RADAR_NODE_IDS`** on the broker). Override with **`CHIRP_SSH_USER`**, **`CHIRP_REMOTE_CHIRP`** (e.g. `Documents/Chirp`), or **`CHIRP_ORIN_INVENTORY`**. For password prompts, use `CHIRP_SSH_OPTS="-o ConnectTimeout=15"`.

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

With a **full Chirp clone** that already has `Fusion-Center/.env` (sync from the Xavier, or legacy `Fusion-Center/MQTT-Broker/.env`):

```bash
cd Chirp
./scripts/chirp_runbook_laptop_env.sh
./scripts/chirp_install_shell_rc.sh laptop "$(pwd)"
source ~/.bashrc
```

That writes `Fusion-Center/Laptop/.env` and `start_laptop_trigger.sh` loads it, `Fusion-Center/.env`, or `MQTT-Broker/.env` automatically. If you keep only a partial tree, copy `Fusion-Center/.env` from the Xavier and set `MQTT_HOST` / `MQTT_LAPTOP_PASS` manually.

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
source .venv/bin/activate
pip install -r requirements.txt
./start_server_controller.sh
```

### Step 3 — [XAVIER] Start bird's-eye dashboard

```bash
cd Chirp
./scripts/chirp_runbook_xavier_dashboard.sh
# Dashboard → http://<xavier-ip>:5002
```

If the repo has no `Fusion-Center/dashboard.py`, start it however your tree provides it, using `Fusion-Center/.env` (or `MQTT-Broker/.env`) for credentials and `MQTT_HOST=127.0.0.1` on the Xavier.

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
