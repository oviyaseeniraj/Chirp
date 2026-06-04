#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BROKER_ENV_FILE="${SCRIPT_DIR}/MQTT-Broker/.env"
source "${BROKER_ENV_FILE}" # 'source' command allows bash script to use variables defined in another file

# "export" command makes these variables visible to the child process (child process here is the server_controller.py script)
export MQTT_HOST="${MQTT_HOST:-127.0.0.1}"
export MQTT_PORT="${MQTT_PORT:-1883}"
export MQTT_SERVER_USER="${MQTT_SERVER_USER:-server-xavier}"

if [[ -z "${MQTT_SERVER_PASS:-}" && -z "${MQTT_PASSWORD:-}" ]]; then
  echo "Missing MQTT_SERVER_PASS (or MQTT_PASSWORD). Set it in environment, ${BROKER_ENV_FILE}."
  exit 1
fi

if [[ -n "${MQTT_SERVER_PASS:-}" && -z "${MQTT_PASSWORD:-}" ]]; then
  export MQTT_PASSWORD="${MQTT_SERVER_PASS}"
fi


cleanup() {
  [[ -n "${CTRL_PID:-}" ]] && kill "${CTRL_PID}" 2>/dev/null || true
  [[ -n "${DASH_PID:-}" ]] && kill "${DASH_PID}" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

python3 "${SCRIPT_DIR}/dashboard.py" &
DASH_PID=$!

python3 "${SCRIPT_DIR}/server_controller.py" &
CTRL_PID=$!

# Exit when either process exits; trap will stop the other
wait -n "${DASH_PID}" "${CTRL_PID}"
