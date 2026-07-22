# hardware_trigger_mqtt – Time-Calibration Decoupled

This directory contains the MQTT-controlled hardware trigger subsystem
for Chirp radar nodes.  The architecture has been decoupled so that
**time synchronisation** (periodic ticks) and **calibration** (on-demand
solver runs) operate independently.

## Architecture

| Concern             | Publisher                  | Topic                                 | Frequency      |
|---------------------|----------------------------|---------------------------------------|----------------|
| **Time sync**       | `chirp-timesync` service   | `chirp/v1/group/<gid>/capture/start`  | Every 10 s     |
| **Calibration**     | `chirp-calibration` service| `chirp/v1/group/<gid>/capture/start`  | On demand      |

The node distinguishes them by inspecting `captureConfig.calibration`:

- `calibration: false` (or absent) → **time-sync tick**
- `calibration: true` → **calibration run**

## State Machine

```
                 ┌─────────────┐
          ┌─────▶│    IDLE     │◀──────────────┐
          │      └──────┬──────┘               │
          │             │ time-sync tick       │
          │             │ (calibration=false)  │
          │      ┌──────▼──────┐               │
          │      │   LIVE      │───────────────┤
          │      │  CAPTURE    │  time-sync    │
          │      └──────┬──────┘  tick (re-    │
          │             │         align)       │
          │             │                      │
          │             │ calibration tick     │
          │             │ (calibration=true)   │
          │      ┌──────▼──────┐               │
          │      │ CALIBRATION │               │
          │      │   BURST     ├───────────────┘
          │      └──────┬──────┘  burst done →
          │             │         back to LIVE
          └─────────────┘
```

- **IDLE** → **LIVE**:  on first time-sync tick.
- **LIVE** → **LIVE**:  on each time-sync tick (re-align epoch).
- **LIVE** → **CALIBRATION**:  on calibration `capture/start`.
- **CALIBRATION** → **LIVE**:  after publishing `calibration/done`.
- **Any** → **IDLE**:  on error or explicit stop command.

## Components

- `trigger_worker` – C real-time GPIO pulse generator (SCHED_FIFO, CPU-pinned)
- `mqtt_trigger_client.py` – Python MQTT client: subscribes to commands,
  manages worker lifecycle, publishes presence/state/ack
- `command_cache.py` – TTL-based deduplication for command IDs

## Build

From this directory:

```
make
```

## Run

### Trigger Worker (direct)

```
./trigger_worker --start-epoch-ms <epoch_ms>
```

Optional arguments:

- `--pulse-period-ms <ms>` (default: 50)
- `--max-pulses <n>` (default: run forever — live capture)
- `--cpu-core <id>` (default: 5)
- `--quiet` — suppress per-pulse output (recommended for live capture)

Example (trigger 5 seconds in the future):

```
./trigger_worker --start-epoch-ms $(( $(date +%s%3N) + 5000 ))
```

### MQTT Control Client

Environment (defaults shown):

- `MQTT_HOST=127.0.0.1`
- `MQTT_PORT=1883`
- `NODE_ID=$(hostname)`
- `GROUP_ID=default`
- `MQTT_CLIENT_ID=radar-${NODE_ID}`
- `MQTT_USERNAME=${NODE_ID}`
- `MQTT_PASSWORD=`
- `CHIRP_SCHEMA_VERSION=1`
- `TRIGGER_WORKER_PATH=./trigger_worker`
- `PRESENCE_HEARTBEAT_MS=2000`
- `COMMAND_CACHE_TTL_MS=300000`
- `COMMAND_REPLAY_MAX_AGE_MS=30000`
- `COMMAND_START_LATE_GRACE_MS=250`
- `COMMAND_START_FUTURE_MAX_SKEW_MS=600000`
- `TIMESYNC_LATE_GRACE_MS=5250` (extended tolerance for time-sync ticks)

Run the MQTT trigger client:

```
sudo -E /home/chirp/Chirp/Node/.venv/bin/python3 mqtt_trigger_client.py
```

The `-E` flag preserves environment variables; `sudo` is required so
`trigger_worker` inherits privileges for GPIO access.

## Subscribed Topics

| Topic                                            | Purpose                     |
|--------------------------------------------------|-----------------------------|
| `chirp/v1/group/<gid>/capture/start`             | Time-sync tick + calib cmd  |
| `chirp/v1/group/<gid>/calibration/result`        | Apply calibration matrix    |
| `chirp/v1/group/<gid>/node/<nid>/command`        | Dashboard debug commands    |

## Published Topics

| Topic                                             | When                                |
|---------------------------------------------------|-------------------------------------|
| `chirp/v1/presence/<nid>`                         | On connect / periodic heartbeat     |
| `chirp/v1/group/<gid>/capture/state/<nid>`        | State change (idle / live / calib)  |
| `chirp/v1/group/<gid>/capture/ack/<nid>`          | ACK every capture/start             |

## New Node Join Flow

1. Publish presence: `chirp/v1/presence/<nid>`  (`status: "online"`)
2. State: `chirp/v1/group/<gid>/capture/state/<nid>`  (`state: "idle"`)
3. Within ≤10 s receive a time-sync `capture/start` from the timesync service.
4. Immediately begin hardware frame collection — no calibration required.
5. At any later time a calibration run may be triggered; the node
   participates and applies the resulting calibration matrix.

## Compatibility

- The message schema is **unchanged** — nodes that already handle
  the existing `capture/start` format work without protocol changes.
- Nodes now do **not** require calibration before starting live capture.
  They apply an identity (no-op) calibration until a real result arrives.
- The most recent calibration result is stored and applied to live frames.
