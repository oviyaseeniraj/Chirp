#!/usr/bin/env bash
# [XAVIER] Part 1 Step 3 — bird's-eye dashboard with MQTT_HOST=127.0.0.1 and credentials from broker .env.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FC="${REPO_ROOT}/Fusion-Center"
BROKER_ENV="${FC}/MQTT-Broker/.env"
DASHBOARD="${FC}/dashboard.py"

[[ -f "${BROKER_ENV}" ]] || { echo "Missing ${BROKER_ENV}" >&2; exit 1; }

if [[ ! -f "${DASHBOARD}" ]]; then
  echo "No ${DASHBOARD} in this checkout — start dashboard manually per your deployment." >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "${BROKER_ENV}"
export MQTT_HOST=127.0.0.1
export DASHBOARD_PORT="${DASHBOARD_PORT:-5002}"
if [[ -z "${MQTT_SERVER_PASS:-}" && -n "${MQTT_PASSWORD:-}" ]]; then
  export MQTT_SERVER_PASS="${MQTT_PASSWORD}"
fi
set +a

cd "${FC}"
if [[ -f "${FC}/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "${FC}/.venv/bin/activate"
fi

exec python3 "${DASHBOARD}"
