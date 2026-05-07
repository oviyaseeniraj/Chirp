#!/usr/bin/env bash
# Print env vars to set for your LAN (broker IP from this host or argv).
# Usage: ./chirp_print_env_reference.sh [broker_ipv4]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
broker_ip="${1:-}"
if [[ -z "${broker_ip}" ]]; then
  broker_ip="$("${SCRIPT_DIR}/chirp_detect_lan_ipv4.sh")"
fi

cat <<EOF
# From your current LAN (wlan0), the fusion-center / broker host is reachable at ${broker_ip}.

# --- On each Orin (Node/.env or exports) ---
MQTT_HOST=${broker_ip}
MQTT_PORT=1883
NODE_ID=node1                    # unique per Orin — use same string below
GROUP_ID=default
MQTT_USERNAME=node1              # normally same as NODE_ID
MQTT_PASSWORD=<same as MQTT_RADAR_PASSWORD in Fusion-Center/MQTT-Broker/.env>
MQTT_CLIENT_ID=radar-node1       # radar- plus NODE_ID

# --- On laptop (exports or Fusion-Center/MQTT-Broker/.env + extras) ---
MQTT_HOST=${broker_ip}
MQTT_LAPTOP_USER=laptop-control
MQTT_LAPTOP_PASS=<from broker .env>
DASHBOARD_PORT=5002

# --- On Xavier for dashboard/server on the same machine (optional; localhost avoids routing) ---
MQTT_HOST=127.0.0.1
MQTT_SERVER_PASS=<from broker .env>
EOF
