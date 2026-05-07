#!/usr/bin/env bash
# Print a URL- and sed-safe random secret (hex).
# Usage: chirp_random_hex.sh [num_bytes]   default 24 -> 48 hex chars
set -euo pipefail
n="${1:-24}"
openssl rand -hex "${n}"
