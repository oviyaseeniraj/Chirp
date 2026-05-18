#!/usr/bin/env bash
# [LAPTOP] Part 0 — write Laptop/.env from broker file (full Chirp clone).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${SCRIPT_DIR}/chirp_write_laptop_env.sh"
