#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <group_id> <node_id> [broker_host] [broker_port]"
  exit 1
fi

GROUP_ID="$1"
NODE_ID="$2"
BROKER_HOST="${3:-127.0.0.1}"
BROKER_PORT="${4:-1883}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}. Copy .env.example to .env and set credentials."
  exit 1
fi

# shellcheck disable=SC1090
source "${ENV_FILE}"

: "${MQTT_SERVER_USER:?Missing MQTT_SERVER_USER in .env}"
: "${MQTT_SERVER_PASS:?Missing MQTT_SERVER_PASS in .env}"

publish_clear() {
  local topic="$1"
  mosquitto_pub \
    -h "${BROKER_HOST}" \
    -p "${BROKER_PORT}" \
    -u "${MQTT_SERVER_USER}" \
    -P "${MQTT_SERVER_PASS}" \
    -t "${topic}" \
    -n \
    -r
  echo "Cleared retained topic: ${topic}"
}

publish_clear "chirp/v1/presence/${NODE_ID}"
publish_clear "chirp/v1/group/${GROUP_ID}/capture/state/${NODE_ID}"
