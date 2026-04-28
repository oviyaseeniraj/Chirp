#!/usr/bin/env bash
# If broker .env still has the example placeholder passwords, replace them with random secrets.
# Idempotent: does nothing if values were already changed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:?path to MQTT-Broker/.env}"

[[ -f "${ENV_FILE}" ]] || { echo "Missing ${ENV_FILE}" >&2; exit 1; }

_get() { "${SCRIPT_DIR}/chirp_env_get.sh" "${ENV_FILE}" "$1"; }

patch_if_placeholder() {
  local key="$1" placeholder="$2"
  local cur
  cur="$(_get "${key}")"
  if [[ "${cur}" == "${placeholder}" ]]; then
    local secret
    secret="$("${SCRIPT_DIR}/chirp_random_hex.sh" 18)"
    "${SCRIPT_DIR}/chirp_patch_env_key.sh" "${ENV_FILE}" "${key}" "${secret}"
    echo "Replaced placeholder ${key} with a generated secret (see ${ENV_FILE})" >&2
  fi
}

patch_if_placeholder MQTT_LAPTOP_PASS "change-me-laptop"
patch_if_placeholder MQTT_SERVER_PASS "change-me-server"
patch_if_placeholder MQTT_RADAR_PASSWORD "change-me-radar-shared"
