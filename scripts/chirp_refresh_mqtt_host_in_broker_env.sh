#!/usr/bin/env bash
# If MQTT_HOST in broker .env is missing, X.X.X.X, or 0.0.0.0, set it to this machine's LAN IP.
# Called from start_broker.sh so runbook Step 1 auto-fixes stale examples.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:?path to broker .env}"

[[ -f "${ENV_FILE}" ]] || exit 0

cur="$("${SCRIPT_DIR}/chirp_env_get.sh" "${ENV_FILE}" MQTT_HOST || true)"
if [[ -z "${cur}" || "${cur}" == "X.X.X.X" || "${cur}" == "0.0.0.0" ]]; then
  lan_ip="$("${SCRIPT_DIR}/chirp_detect_lan_ipv4.sh")"
  "${SCRIPT_DIR}/chirp_patch_env_key.sh" "${ENV_FILE}" MQTT_HOST "${lan_ip}"
  printf '%s\n' "${lan_ip}" >"$(cd "${SCRIPT_DIR}/.." && pwd)/.chirp_broker_ip"
  echo "chirp_refresh_mqtt_host: set MQTT_HOST=${lan_ip} in ${ENV_FILE}" >&2
fi
