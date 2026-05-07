#!/usr/bin/env bash
# Print the value for KEY in a dotenv file (first match; strip inline comments and whitespace).
# Usage: chirp_env_get.sh /path/to/.env MQTT_HOST
set -euo pipefail

file="${1:?env file}"
key="${2:?key}"

[[ -f "${file}" ]] || exit 1

awk -F= -v k="$key" '
  $1 == k {
    line = $0
    sub(/^[^=]*=/, "", line)
    sub(/#.*/, "", line)
    gsub(/^[ \t]+|[ \t]+$/, "", line)
    print line
    exit
  }
' "${file}"
