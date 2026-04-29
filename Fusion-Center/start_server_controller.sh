#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}. Copy Fusion-Center/.env.example to .env and set all values (especially MQTT_HOST as the Xavier LAN IP, not X.X.X.X)." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${ENV_FILE}"

export MQTT_HOST="${MQTT_HOST:-127.0.0.1}"
export MQTT_PORT="${MQTT_PORT:-1883}"

if [[ "${MQTT_HOST}" == "X.X.X.X" ]]; then
  echo "MQTT_HOST is still the placeholder X.X.X.X. Set it in ${ENV_FILE} to the broker IPv4 (e.g. 169.231.46.13)." >&2
  exit 1
fi

if [[ -z "${MQTT_SERVER_PASS:-}" && -z "${MQTT_PASSWORD:-}" ]]; then
  echo "Missing MQTT_SERVER_PASS or MQTT_PASSWORD in ${ENV_FILE}." >&2
  exit 1
fi

if [[ -n "${MQTT_SERVER_PASS:-}" && -z "${MQTT_PASSWORD:-}" ]]; then
  export MQTT_PASSWORD="${MQTT_SERVER_PASS}"
fi

exec python3 "${SCRIPT_DIR}/server_controller.py"
