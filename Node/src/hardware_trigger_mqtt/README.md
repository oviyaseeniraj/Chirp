# hardware_trigger_mqtt (Phase 1 + Phase 2 + Phase 3)

This directory contains the isolated Step 3 rollout artifacts:

- Phase 1: absolute-time hardware trigger worker (`trigger_worker`)
- Phase 2: MQTT control client (`mqtt_trigger_client.py`)
- Phase 3: command dedup + replay protection (`command_cache.py`)

## Scope

Phase 1 and Phase 2 are implemented here without modifying legacy files under
`src/hardware_trigger`.

Legacy trigger code in `src/hardware_trigger` remains untouched.

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

- `--pulse-period-ms <ms>` (default: 100)
- `--max-pulses <n>` (default: run forever)
- `--cpu-core <id>` (default: 5)

Example (trigger 5 seconds in the future):

```
./trigger_worker --start-epoch-ms $(( $(date +%s%3N) + 5000 ))
```

### MQTT Control Client

The MQTT client subscribes to:

- `chirp/v1/group/<groupId>/capture/start`

And publishes:

- `chirp/v1/presence/<nodeId>` (retained)
- `chirp/v1/group/<groupId>/capture/state/<nodeId>` (retained)
- `chirp/v1/group/<groupId>/capture/ack/<nodeId>` (non-retained)

Environment (defaults shown):

- `MQTT_HOST=127.0.0.1`
- `MQTT_PORT=1883`
- `NODE_ID=$(hostname)`
- `GROUP_ID=default`
- `MQTT_CLIENT_ID=radar-${NODE_ID}`
- `MQTT_USERNAME=${NODE_ID}`
- `MQTT_PASSWORD=`
- `CHIRP_SCHEMA_VERSION=1`
- `TRIGGER_WORKER_PATH=./trigger_worker` (auto-resolved to this directory by default)
- `PRESENCE_HEARTBEAT_MS=2000`
- `COMMAND_CACHE_TTL_MS=300000`
- `COMMAND_REPLAY_MAX_AGE_MS=30000`
- `COMMAND_START_LATE_GRACE_MS=250`
- `COMMAND_START_FUTURE_MAX_SKEW_MS=600000`

Phase 3 behavior:
- Duplicate `commandId` values within cache TTL are ignored (no second worker launch).
- Stale start commands (`startEpochMs` too far in the past) are rejected.
- Replayed payloads with stale `timestampMs` are rejected.

If you get an error about the socket connection timing out, the env variable for MQTT_HOST might be off. 
Do `sudo vim ~/.bashrc` and see if the following lines are pasted in at the very bottom of the file:

```
# when opening up a new terminal on the radar node, ensure that env variables used in mqtt_trigger_client.py are sourced from Node/.env
set -a                                  # auto exports all loaded vars so Python sees them via os.getenv
source /home/chirp/Chirp/Node/.env      
set +a
```

This section of Bash code ensure that when opening up a terminal on a radar node, environment variables will be sourced from that .env file. 

Run the MQTT trigger client using the python interpreter defined in the virtual environment, and keep environment variables with the `-E` flag. Need to run as `sudo` so `trigger_worker.c` inherits sudo ownership for GPIO access (necessary for harwdare triggering):
```
sudo -E /home/chirp/Chirp/Node/.venv/bin/python3 mqtt_trigger_client.py
```
