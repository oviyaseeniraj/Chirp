## Step 4: Laptop trigger CLI

Use the laptop-side CLI to publish one start request and wait for matching result.

Files:
- `Fusion-Center/laptop_trigger_client.py`
- `Fusion-Center/start_laptop_trigger.sh`

Basic usage:
- `cd Fusion-Center`
- `chmod +x start_laptop_trigger.sh`
- `./start_laptop_trigger.sh --group-id default`

Optional flags:
- `--requested-delay-ms 3000`
- `--capture-config-json '{"profile":"demo"}'`
- `--capture-config-file /path/to/capture_config.json`
- `--timeout-ms 12000`
- `--print-json`

Environment inputs:
- `MQTT_HOST` (default `127.0.0.1`)
- `MQTT_PORT` (default `1883`)
- `MQTT_USERNAME` or `MQTT_LAPTOP_USER` (default `laptop-control`)
- `MQTT_PASSWORD` or `MQTT_LAPTOP_PASS` (required)

The CLI publishes to:
- `chirp/v1/server/start/request`

And waits on:
- `chirp/v1/server/start/result`

It correlates responses by `requestId` and exits non-zero if the server returns `ok=false` or if timeout occurs.