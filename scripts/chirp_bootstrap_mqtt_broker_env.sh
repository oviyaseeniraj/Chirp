#!/usr/bin/env bash
# On the Xavier (broker host): ensure MQTT-Broker/.env exists and set MQTT_HOST to this machine's LAN IP.
# Writes repo-root .chirp_broker_ip for other scripts (gitignored).
#
# Usage (from repo root or any cwd):
#   ./scripts/chirp_bootstrap_mqtt_broker_env.sh
#
# Prerequisites: copy MQTT-Broker/.env.example to .env and set passwords, or run once after editing .env manually.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BROKER_DIR="${REPO_ROOT}/Fusion-Center/MQTT-Broker"
ENV_FILE="${BROKER_DIR}/.env"
EXAMPLE="${BROKER_DIR}/.env.example"
IP_FILE="${REPO_ROOT}/.chirp_broker_ip"

if [[ ! -f "${ENV_FILE}" ]]; then
  if [[ ! -f "${EXAMPLE}" ]]; then
    echo "Missing ${EXAMPLE}" >&2
    exit 1
  fi
  cp "${EXAMPLE}" "${ENV_FILE}"
  echo "Created ${ENV_FILE} from example — set MQTT_* passwords and run MQTT-Broker/set_mqttbroker_passwords.sh" >&2
fi

lan_ip="$("${SCRIPT_DIR}/chirp_detect_lan_ipv4.sh")"
"${SCRIPT_DIR}/chirp_patch_env_key.sh" "${ENV_FILE}" MQTT_HOST "${lan_ip}"
printf '%s\n' "${lan_ip}" >"${IP_FILE}"

echo "MQTT_HOST=${lan_ip} in ${ENV_FILE}"
echo "Wrote ${IP_FILE} (use when bootstrapping Orin Node/.env on the same LAN)"
