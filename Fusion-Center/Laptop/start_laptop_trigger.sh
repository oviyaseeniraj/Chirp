#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FUSION_CENTER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
FC_ENV="${FUSION_CENTER_DIR}/.env"
BROKER_ENV_FILE="${FUSION_CENTER_DIR}/MQTT-Broker/.env"
LAPTOP_ENV_FILE="${SCRIPT_DIR}/.env"

if [[ -f "${FC_ENV}" ]]; then
  # shellcheck disable=SC1090
  source "${FC_ENV}"
elif [[ -f "${BROKER_ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${BROKER_ENV_FILE}"
elif [[ -f "${LAPTOP_ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${LAPTOP_ENV_FILE}"
else
  echo "Missing ${FC_ENV}, ${BROKER_ENV_FILE}, or ${LAPTOP_ENV_FILE}."
  echo "On a full clone run: Chirp/scripts/chirp_runbook_laptop_env.sh (after Fusion-Center/.env exists on the Xavier)."
  exit 1
fi

export MQTT_HOST="${MQTT_HOST:-127.0.0.1}"
export MQTT_PORT="${MQTT_PORT:-1883}"
export MQTT_LAPTOP_USER="${MQTT_LAPTOP_USER:-laptop-control}"
export MQTT_LAPTOP_PASS="${MQTT_LAPTOP_PASS:-}"

if [[ -z "${MQTT_LAPTOP_PASS:-}" ]]; then
  echo "Missing MQTT password (MQTT_LAPTOP_PASS)."
  echo "Set it in environment, ${FC_ENV}, or ${BROKER_ENV_FILE}."
  exit 1
fi

exec python3 "${SCRIPT_DIR}/laptop_trigger_client.py" "$@"
