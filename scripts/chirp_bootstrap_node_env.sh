#!/usr/bin/env bash
# On each Orin: create or update Node/.env for MQTT and Node identity.
#
# Usage:
#   ./scripts/chirp_bootstrap_node_env.sh [node_id] [MQTT_HOST]
#
# node_id defaults to CHIRP_NODE_ID or short hostname. MQTT_HOST from arg, CHIRP_BROKER_MQTT_HOST,
# Fusion-Center/MQTT-Broker/.env (same clone), or .chirp_broker_ip.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
NODE_ENV="${REPO_ROOT}/Node/.env"
NODE_EXAMPLE="${REPO_ROOT}/Node/.env.example"
IP_FILE="${REPO_ROOT}/.chirp_broker_ip"
BROKER_ENV="${REPO_ROOT}/Fusion-Center/MQTT-Broker/.env"

node_id="${1:-${CHIRP_NODE_ID:-$(hostname -s)}}"
mqtt_host="${2:-}"

if [[ -z "${mqtt_host}" ]]; then
  mqtt_host="${CHIRP_BROKER_MQTT_HOST:-}"
fi
if [[ -z "${mqtt_host}" && -f "${BROKER_ENV}" ]]; then
  mqtt_host="$("${SCRIPT_DIR}/chirp_env_get.sh" "${BROKER_ENV}" MQTT_HOST || true)"
fi
if [[ -z "${mqtt_host}" && -f "${IP_FILE}" ]]; then
  mqtt_host="$(tr -d ' \t\r\n' <"${IP_FILE}")"
fi
if [[ -z "${mqtt_host}" ]]; then
  echo "Set MQTT_HOST: pass as second arg, export CHIRP_BROKER_MQTT_HOST, or run chirp_bootstrap_mqtt_broker_env.sh on Xavier and copy ${IP_FILE} here." >&2
  exit 1
fi

if [[ ! -f "${NODE_ENV}" ]]; then
  if [[ ! -f "${NODE_EXAMPLE}" ]]; then
    echo "Missing ${NODE_EXAMPLE}" >&2
    exit 1
  fi
  cp "${NODE_EXAMPLE}" "${NODE_ENV}"
  echo "Created ${NODE_ENV} from example — fill Supabase keys if you use them." >&2
fi

"${SCRIPT_DIR}/chirp_patch_env_key.sh" "${NODE_ENV}" MQTT_HOST "${mqtt_host}"
"${SCRIPT_DIR}/chirp_patch_env_key.sh" "${NODE_ENV}" NODE_ID "${node_id}"
"${SCRIPT_DIR}/chirp_patch_env_key.sh" "${NODE_ENV}" MQTT_USERNAME "${node_id}"
"${SCRIPT_DIR}/chirp_patch_env_key.sh" "${NODE_ENV}" MQTT_CLIENT_ID "radar-${node_id}"
"${SCRIPT_DIR}/chirp_patch_env_key.sh" "${NODE_ENV}" GROUP_ID "${GROUP_ID:-default}"

if [[ -f "${BROKER_ENV}" ]]; then
  radar_pass="$("${SCRIPT_DIR}/chirp_env_get.sh" "${BROKER_ENV}" MQTT_RADAR_PASSWORD || true)"
  if [[ -n "${radar_pass}" ]]; then
    "${SCRIPT_DIR}/chirp_patch_env_key.sh" "${NODE_ENV}" MQTT_PASSWORD "${radar_pass}"
  fi
fi

echo "Updated ${NODE_ENV}: MQTT_HOST=${mqtt_host} NODE_ID=${node_id} MQTT_USERNAME=${node_id} MQTT_CLIENT_ID=radar-${node_id}"
