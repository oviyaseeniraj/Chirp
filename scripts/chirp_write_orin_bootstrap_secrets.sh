#!/usr/bin/env bash
# Write repo-root files Orins can copy (with .chirp_broker_ip) so Node/.env needs no hand editing:
#   .chirp_radar_mqtt_password  — same value as MQTT_RADAR_PASSWORD in MQTT-Broker/.env
#
# Run after broker .env is final (e.g. end of chirp_runbook_xavier_mqtt.sh).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BROKER_ENV="${REPO_ROOT}/Fusion-Center/MQTT-Broker/.env"
OUT="${REPO_ROOT}/.chirp_radar_mqtt_password"

[[ -f "${BROKER_ENV}" ]] || { echo "Missing ${BROKER_ENV}" >&2; exit 1; }

radar_pass="$("${SCRIPT_DIR}/chirp_env_get.sh" "${BROKER_ENV}" MQTT_RADAR_PASSWORD || true)"
if [[ -z "${radar_pass}" ]]; then
  echo "No MQTT_RADAR_PASSWORD in ${BROKER_ENV}" >&2
  exit 1
fi

umask 077
printf '%s\n' "${radar_pass}" >"${OUT}"
echo "Wrote ${OUT} (copy to each Orin repo root with .chirp_broker_ip; both are gitignored)" >&2
