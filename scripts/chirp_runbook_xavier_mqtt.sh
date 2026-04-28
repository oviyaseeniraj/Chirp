#!/usr/bin/env bash
# [XAVIER] Part 0 — MQTT broker .env, LAN IP, secrets, and mosquitto password file (replaces manual cp + edit + set_mqttbroker_passwords).
# Run from anywhere:
#   /path/to/Chirp/scripts/chirp_runbook_xavier_mqtt.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BROKER_DIR="${REPO_ROOT}/Fusion-Center/MQTT-Broker"

for f in "${SCRIPT_DIR}/chirp_"*.sh; do
  [[ -f "${f}" ]] || continue
  chmod +x "${f}"
done
for f in "${BROKER_DIR}/"*.sh; do
  [[ -f "${f}" ]] || continue
  chmod +x "${f}"
done

"${SCRIPT_DIR}/chirp_bootstrap_mqtt_broker_env.sh"
"${SCRIPT_DIR}/chirp_ensure_broker_passwords.sh" "${BROKER_DIR}/.env"

echo "Applying credentials to Mosquitto password file (requires sudo if not using local mosquitto_passwd)..." >&2
sudo "${BROKER_DIR}/set_mqttbroker_passwords.sh"

"${SCRIPT_DIR}/chirp_write_orin_bootstrap_secrets.sh"

echo "Done. Broker .env: ${BROKER_DIR}/.env"
echo "Tip: Push env to every Orin over SSH (edit scripts/chirp_orin_inventory.txt if IPs change):"
echo "       ./scripts/chirp_bootstrap_all_orins.sh"
