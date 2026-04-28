#!/usr/bin/env bash

# High level overview:
  # check if 'passwords' file exists
  # if it does, then make a Chirp/MQTT-Broker/data and Chirp/MQTT-Broker/log folder
  # then, run the docker container using docker compose

set -euo pipefail

# Check for root privilege
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (sudo)" 
   exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
REFRESH="${REPO_ROOT}/scripts/chirp_refresh_mqtt_host_in_broker_env.sh"
if [[ -f "${REFRESH}" ]]; then
  bash "${REFRESH}" "${SCRIPT_DIR}/.env" || true
fi

if [[ ! -f "${SCRIPT_DIR}/passwords" ]]; then
  echo "Missing passwords file. Run ./set_mqttbroker_passwords.sh first."
  exit 1
fi

mkdir -p "${SCRIPT_DIR}/data" "${SCRIPT_DIR}/log"

if command -v docker >/dev/null 2>&1 && command -v docker compose >/dev/null 2>&1; then
  docker compose -f "${SCRIPT_DIR}/docker-compose.yaml" up -d # "up" starts the services defined in the docker-compose file, and "-d" means detached mode (run in background)
  
    # Ensure log files are readable by owner, group, and individuals
  chmod 644 "${SCRIPT_DIR}/log/"*.log 2>/dev/null || true

  echo "Mosquitto started (docker compose)."
  exit 0
fi

echo "docker compose not found. Install Docker or start Mosquitto manually."
exit 1
