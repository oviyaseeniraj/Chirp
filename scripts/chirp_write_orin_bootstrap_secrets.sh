#!/usr/bin/env bash
# Write repo-root .chirp_radar_mqtt_password from Fusion-Center/.env (or legacy MQTT-Broker/.env) for scripts that still copy it to Orins.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FC_ENV="${REPO_ROOT}/Fusion-Center/.env"
BROKER_ENV="${REPO_ROOT}/Fusion-Center/MQTT-Broker/.env"
OUT="${REPO_ROOT}/.chirp_radar_mqtt_password"

ENV_SRC=""
if [[ -f "${FC_ENV}" ]]; then
  ENV_SRC="${FC_ENV}"
elif [[ -f "${BROKER_ENV}" ]]; then
  ENV_SRC="${BROKER_ENV}"
else
  echo "Missing ${FC_ENV} (or ${BROKER_ENV})" >&2
  exit 1
fi

radar_pass="$("${SCRIPT_DIR}/chirp_env_get.sh" "${ENV_SRC}" MQTT_RADAR_PASSWORD || true)"
if [[ -z "${radar_pass}" ]]; then
  echo "No MQTT_RADAR_PASSWORD in ${ENV_SRC}" >&2
  exit 1
fi

umask 077
printf '%s\n' "${radar_pass}" >"${OUT}"
echo "Wrote ${OUT} (optional: copy to each Orin repo root with .chirp_broker_ip; both are gitignored)" >&2
