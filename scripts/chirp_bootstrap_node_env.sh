#!/usr/bin/env bash
# On each Orin: ensure Node/.env exists; you must edit MQTT_HOST, NODE_ID, and MQTT credentials by hand (or copy from Fusion-Center/.env on the Xavier).
#
# Usage (optional args are ignored):
#   ./scripts/chirp_bootstrap_node_env.sh [node_id] [MQTT_HOST]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
NODE_ENV="${REPO_ROOT}/Node/.env"
NODE_EXAMPLE="${REPO_ROOT}/Node/.env.example"

if [[ ! -f "${NODE_ENV}" ]]; then
  if [[ ! -f "${NODE_EXAMPLE}" ]]; then
    echo "Missing ${NODE_EXAMPLE}" >&2
    exit 1
  fi
  cp "${NODE_EXAMPLE}" "${NODE_ENV}"
  echo "Created ${NODE_ENV} from ${NODE_EXAMPLE}." >&2
fi

echo "Edit ${NODE_ENV}: set MQTT_HOST (Xavier IPv4), NODE_ID, MQTT_USERNAME, MQTT_PASSWORD, MQTT_CLIENT_ID=radar-\$NODE_ID, GROUP_ID, CHIRP_SCHEMA_VERSION, and Supabase keys if used." >&2
if [[ $# -gt 0 ]]; then
  echo "(Note: positional arguments are no longer applied automatically — update the file above.)" >&2
fi
