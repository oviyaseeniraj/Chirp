# hardware_trigger_mqtt (Phase 1)

This directory contains the isolated Phase 1 trigger worker for Step 3 rollout.

## Scope

Phase 1 only refactors the trigger execution path to accept an absolute start time.
No MQTT client logic is implemented in this directory yet.

Legacy trigger code in `src/hardware_trigger` remains untouched.

## Build

From this directory:

```
make
```

## Run

Required argument:

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

Note: `$(date +%s%3N)` gives the current clock time since UNIX epoch time in milliseconds (without `%3N` returns the time in seconds)