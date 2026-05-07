#!/usr/bin/env bash
# From a machine with SSH to each Orin: copy .chirp_radar_mqtt_password and run chirp_runbook_orin_env.sh on every line in chirp_orin_inventory.txt.
#
# Broker IPv4 is read from Fusion-Center/.env (MQTT_HOST), or from repo-root .chirp_broker_ip if present.
#
# Usage:
#   ./scripts/chirp_bootstrap_all_orins.sh
#   CHIRP_SSH_USER=you CHIRP_REMOTE_CHIRP=Documents/Chirp ./scripts/chirp_bootstrap_all_orins.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INV="${CHIRP_ORIN_INVENTORY:-${SCRIPT_DIR}/chirp_orin_inventory.txt}"
IP_FILE="${REPO_ROOT}/.chirp_broker_ip"
RADAR_FILE="${REPO_ROOT}/.chirp_radar_mqtt_password"
FC_ENV="${REPO_ROOT}/Fusion-Center/.env"
REMOTE_DIR="${CHIRP_REMOTE_CHIRP:-Chirp}"
SSH_USER="${CHIRP_SSH_USER:-chirp}"
SSH_OPTS="${CHIRP_SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=15}"

[[ -f "${INV}" ]] || { echo "Missing inventory: ${INV}" >&2; exit 1; }

broker_ip=""
if [[ -f "${FC_ENV}" ]]; then
  broker_ip="$("${SCRIPT_DIR}/chirp_env_get.sh" "${FC_ENV}" MQTT_HOST || true)"
fi
if [[ -z "${broker_ip}" && -f "${IP_FILE}" ]]; then
  broker_ip="$(tr -d ' \t\r\n' <"${IP_FILE}")"
fi
[[ -n "${broker_ip}" ]] || {
  echo "Could not read broker IP. Set MQTT_HOST in ${FC_ENV} or create ${IP_FILE} with one IPv4 line." >&2
  exit 1
}

umask 077
printf '%s\n' "${broker_ip}" >"${IP_FILE}"

if [[ ! -f "${RADAR_FILE}" ]]; then
  if [[ -f "${FC_ENV}" ]]; then
    rp="$("${SCRIPT_DIR}/chirp_env_get.sh" "${FC_ENV}" MQTT_RADAR_PASSWORD || true)"
    if [[ -n "${rp}" ]]; then
      printf '%s\n' "${rp}" >"${RADAR_FILE}"
    fi
  fi
fi
[[ -f "${RADAR_FILE}" ]] || {
  echo "Missing ${RADAR_FILE} — run scripts/chirp_runbook_xavier_mqtt.sh on the Xavier (or add MQTT_RADAR_PASSWORD to Fusion-Center/.env and re-run chirp_write_orin_bootstrap_secrets.sh)." >&2
  exit 1
}

while read -r node_id ip; do
  [[ -z "${node_id}" ]] && continue
  echo "---- ${node_id} @ ${ip} ----" >&2
  remote="${SSH_USER}@${ip}"
  rtarget="${remote}:${REMOTE_DIR}/"
  scp ${SSH_OPTS} -p "${IP_FILE}" "${RADAR_FILE}" "${rtarget}"
  ssh ${SSH_OPTS} "${remote}" "cd \"\${HOME}/${REMOTE_DIR}\" && for f in scripts/chirp_*.sh; do [[ -f \"\$f\" ]] && chmod +x \"\$f\"; done; ./scripts/chirp_runbook_orin_env.sh '${node_id}'"
done < <(awk '!/^#/ && NF >= 2 { print $1, $2 }' "${INV}")

echo "Done. Touched Orins listed in ${INV} (ensure each Node/.env matches that node's identity)." >&2
