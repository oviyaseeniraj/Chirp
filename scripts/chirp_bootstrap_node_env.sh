#!/usr/bin/env bash
# On each Orin: create or update Node/.env for MQTT and Node identity.
#
# Usage:
#   ./scripts/chirp_bootstrap_node_env.sh [node_id] [MQTT_HOST]
#
# node_id defaults to CHIRP_NODE_ID or short hostname. MQTT_HOST from arg, CHIRP_BROKER_MQTT_HOST,
# CHIRP_BROKER_IP_FILE, Fusion-Center/MQTT-Broker/.env, .chirp_broker_ip, or IPv4 from chrony (Xavier NTP).
# Interactive: if still unknown and stdin is a TTY, prompts once for the broker IP.
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
if [[ -z "${mqtt_host}" && -n "${CHIRP_BROKER_IP_FILE:-}" && -f "${CHIRP_BROKER_IP_FILE}" ]]; then
  mqtt_host="$(tr -d ' \t\r\n' <"${CHIRP_BROKER_IP_FILE}")"
fi
if [[ -z "${mqtt_host}" && -f "${BROKER_ENV}" ]]; then
  mqtt_host="$("${SCRIPT_DIR}/chirp_env_get.sh" "${BROKER_ENV}" MQTT_HOST || true)"
fi
if [[ -z "${mqtt_host}" && -f "${IP_FILE}" ]]; then
  mqtt_host="$(tr -d ' \t\r\n' <"${IP_FILE}")"
fi
if [[ -z "${mqtt_host}" ]]; then
  if guess="$("${SCRIPT_DIR}/chirp_guess_broker_ip_from_chrony.sh" 2>/dev/null)"; then
    mqtt_host="${guess}"
    echo "Using broker IP from chrony: ${mqtt_host}" >&2
  fi
fi
if [[ -z "${mqtt_host}" && -t 0 ]]; then
  read -r -p "Enter Xavier / MQTT broker IPv4 (no hostname): " mqtt_host
  mqtt_host="$(echo "${mqtt_host}" | tr -d ' \t\r\n')"
fi
if [[ -z "${mqtt_host}" ]]; then
  echo "Could not set MQTT_HOST. Examples:" >&2
  echo "  CHIRP_BROKER_MQTT_HOST=169.231.x.x ./scripts/chirp_runbook_orin_env.sh ${node_id}" >&2
  echo "  ./scripts/chirp_runbook_orin_env.sh ${node_id} 169.231.x.x" >&2
  echo "  scp xavier:Chirp/.chirp_broker_ip ${IP_FILE}" >&2
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

pass_val="$("${SCRIPT_DIR}/chirp_env_get.sh" "${NODE_ENV}" MQTT_PASSWORD || true)"
if [[ -z "${pass_val}" || "${pass_val}" == "change-me-radar" ]]; then
  echo "Reminder: set MQTT_PASSWORD in ${NODE_ENV} to MQTT_RADAR_PASSWORD from the Xavier (no usable broker .env here)." >&2
fi

echo "Updated ${NODE_ENV}: MQTT_HOST=${mqtt_host} NODE_ID=${node_id} MQTT_USERNAME=${node_id} MQTT_CLIENT_ID=radar-${node_id}"
