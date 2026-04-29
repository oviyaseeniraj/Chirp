#!/usr/bin/env bash
# [XAVIER] Part 0 — Apply Mosquitto passwords from Fusion-Center/.env (single source of truth).
# Create Fusion-Center/.env from Fusion-Center/.env.example first; then run:
#   /path/to/Chirp/scripts/chirp_runbook_xavier_mqtt.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BROKER_DIR="${REPO_ROOT}/Fusion-Center/MQTT-Broker"
FC_ENV="${REPO_ROOT}/Fusion-Center/.env"

for f in "${SCRIPT_DIR}/chirp_"*.sh; do
  [[ -f "${f}" ]] || continue
  chmod +x "${f}"
done
for f in "${BROKER_DIR}/"*.sh; do
  [[ -f "${f}" ]] || continue
  chmod +x "${f}"
done

if [[ ! -f "${FC_ENV}" ]]; then
  echo "Missing ${FC_ENV}. Copy Fusion-Center/.env.example to Fusion-Center/.env and set MQTT_HOST (broker IPv4), passwords, and Supabase keys." >&2
  exit 1
fi

"${SCRIPT_DIR}/chirp_ensure_broker_passwords.sh" "${FC_ENV}"

echo "Applying credentials to Mosquitto password file (requires sudo if not using local mosquitto_passwd)..." >&2
sudo "${BROKER_DIR}/set_mqttbroker_passwords.sh"

"${SCRIPT_DIR}/chirp_write_orin_bootstrap_secrets.sh"

echo "Done. Env file: ${FC_ENV}"
echo "Optional: push broker IP + radar password hints to Orins (edit scripts/chirp_orin_inventory.txt):"
echo "       ./scripts/chirp_bootstrap_all_orins.sh"
