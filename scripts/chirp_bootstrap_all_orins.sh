#!/usr/bin/env bash
# From the Xavier (or any host with SSH to each Orin): copy .chirp_broker_ip + .chirp_radar_mqtt_password
# and run chirp_runbook_orin_env.sh on every line in chirp_orin_inventory.txt.
#
# Prereqs: SSH keys to each Orin as CHIRP_SSH_USER; repo on each at ~/CHIRP_REMOTE_CHIRP (default ~/Chirp);
#          run ./scripts/chirp_runbook_xavier_mqtt.sh here first so both bootstrap files exist.
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
REMOTE_DIR="${CHIRP_REMOTE_CHIRP:-Chirp}"
SSH_USER="${CHIRP_SSH_USER:-chirp}"
SSH_OPTS="${CHIRP_SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=15}"

[[ -f "${INV}" ]] || { echo "Missing inventory: ${INV}" >&2; exit 1; }
[[ -f "${IP_FILE}" ]] || { echo "Missing ${IP_FILE} — run scripts/chirp_runbook_xavier_mqtt.sh on the Xavier first." >&2; exit 1; }
[[ -f "${RADAR_FILE}" ]] || {
  echo "Missing ${RADAR_FILE} — run scripts/chirp_runbook_xavier_mqtt.sh or scripts/chirp_write_orin_bootstrap_secrets.sh" >&2
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

echo "Done. Bootstrapped Orins listed in ${INV}" >&2
