#!/usr/bin/env bash
# [ORIN] Part 0 — create/update Node/.env (MQTT host, node id, MQTT_PASSWORD from broker file if present on this clone).
#
# Usage:
#   ./scripts/chirp_runbook_orin_env.sh [NODE_ID] [MQTT_HOST]
#
# Defaults: NODE_ID from CHIRP_NODE_ID or hostname; broker IP from Fusion-Center/.../.env, .chirp_broker_ip, or arg 2.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for f in "${SCRIPT_DIR}/chirp_"*.sh; do
  [[ -f "${f}" ]] || continue
  chmod +x "${f}"
done
"${SCRIPT_DIR}/chirp_bootstrap_node_env.sh" "$@"
