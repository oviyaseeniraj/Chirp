#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FUSION_CENTER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BROKER_ENV_FILE="${FUSION_CENTER_DIR}/MQTT-Broker/.env"

if [[ -f "${BROKER_ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${BROKER_ENV_FILE}"
fi

export MQTT_HOST="${MQTT_HOST:-127.0.0.1}"
export MQTT_PORT="${MQTT_PORT:-1883}"
export MQTT_LAPTOP_USER="${MQTT_LAPTOP_USER:-laptop-control}"

if [[ -z "${MQTT_LAPTOP_PASS:-}" ]]; then
  echo "Missing MQTT password (MQTT_LAPTOP_PASS)."
  echo "Set it in environment, ${BROKER_ENV_FILE}."
  exit 1
fi

exec python3 "${SCRIPT_DIR}/laptop_trigger_client.py" "$@"
