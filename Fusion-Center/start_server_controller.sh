#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
BROKER_ENV_FILE="${SCRIPT_DIR}/MQTT-Broker/.env"

if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
elif [[ -f "${BROKER_ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${BROKER_ENV_FILE}" # 'source' command allows bash script to use variables defined in another file
fi

# "export" command makes these variables visible to the child process (child process here is the server_controller.py script)
export MQTT_HOST="${MQTT_HOST:-127.0.0.1}"
export MQTT_PORT="${MQTT_PORT:-1883}"
export MQTT_SERVER_USER="${MQTT_SERVER_USER:-server-xavier}"

if [[ -z "${MQTT_SERVER_PASS:-}" && -z "${MQTT_PASSWORD:-}" ]]; then
  echo "Missing MQTT_SERVER_PASS (or MQTT_PASSWORD). Set it in environment, ${ENV_FILE}, or ${BROKER_ENV_FILE}."
  exit 1
fi

if [[ -n "${MQTT_SERVER_PASS:-}" && -z "${MQTT_PASSWORD:-}" ]]; then
  export MQTT_PASSWORD="${MQTT_SERVER_PASS}"
fi

exec python3 "${SCRIPT_DIR}/server_controller.py"