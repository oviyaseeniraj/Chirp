#!/usr/bin/env bash

# High level explanation
  # read in all environment variables from .env
  # utilize mosquitto_pwd executable (CLI tool) env variables to configure Mosquitto as the MQTT broker (all this occurs thru Docker container)

# set 3 safety settings in this bash script
set -euo pipefail 

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
PASSWORD_FILE="${SCRIPT_DIR}/passwords" # path to password file on LOCAL computer
PASSWORD_FILE_CMD="${PASSWORD_FILE}" # path to password file on Docker container

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}. Copy .env.example to .env and set credentials."
  exit 1
fi

# shellcheck disable=SC1090
source "${ENV_FILE}"

required_vars=(
  MQTT_LAPTOP_USER
  MQTT_LAPTOP_PASS
  MQTT_SERVER_USER
  MQTT_SERVER_PASS
  MQTT_RADAR_NODE_IDS
  MQTT_RADAR_PASSWORD
)

for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "Missing required env var: ${var_name}"
    exit 1
  fi
done

# check if mosquitto_passwd CLI tool is installed locally; if not, then use docker to run the CLI tool
pass_cmd=()
if command -v mosquitto_passwd >/dev/null 2>&1; then
  pass_cmd=(mosquitto_passwd)
else
  pass_cmd=(docker run --rm -v "${SCRIPT_DIR}:/work" eclipse-mosquitto:2.0 mosquitto_passwd)
  PASSWORD_FILE_CMD="/work/passwords"
fi

rm -f "${PASSWORD_FILE}"

# create/add credentials in the mosquitto_pwd file; "-b" stands for batch mode (non-interactive) and "-c" creates a NEW password file (ovewrites the old one if present)
"${pass_cmd[@]}" -b -c "${PASSWORD_FILE_CMD}" "${MQTT_LAPTOP_USER}" "${MQTT_LAPTOP_PASS}"
"${pass_cmd[@]}" -b "${PASSWORD_FILE_CMD}" "${MQTT_SERVER_USER}" "${MQTT_SERVER_PASS}"

# parse list of radar nodes from .env variable MQTT_RADAR_NODE_IDS, clean each node ID, then add each node as MQTT user
IFS=',' read -r -a radar_nodes <<< "${MQTT_RADAR_NODE_IDS}"
for node_id in "${radar_nodes[@]}"; do
  node_trimmed="$(echo "${node_id}" | xargs)"
  if [[ -z "${node_trimmed}" ]]; then
    continue
  fi
  "${pass_cmd[@]}" -b "${PASSWORD_FILE_CMD}" "${node_trimmed}" "${MQTT_RADAR_PASSWORD}"
done

# chmod {owner,group,others}; for example, chmod 600 = read/write access for owner, no access for group, no access for other users
chmod 600 "${PASSWORD_FILE}"
echo "Wrote credentials to ${PASSWORD_FILE}"