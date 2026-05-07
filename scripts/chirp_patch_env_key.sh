#!/usr/bin/env bash
# Set or replace KEY=value in a dotenv-style file (first column KEY= only).
# Usage: chirp_patch_env_key.sh /path/to/.env MQTT_HOST 169.231.46.13
set -euo pipefail

file="${1:?env file path}"
key="${2:?key name}"
value="${3:?value}"

[[ -f "${file}" ]] || { echo "Missing file: ${file}" >&2; exit 1; }

tmp="${file}.tmp.$$"
trap 'rm -f "${tmp}"' EXIT

if grep -q "^${key}=" "${file}"; then
  # shellcheck disable=SC2001
  sed "s|^${key}=.*|${key}=${value}|" "${file}" >"${tmp}"
else
  cp "${file}" "${tmp}"
  printf '%s=%s\n' "${key}" "${value}" >>"${tmp}"
fi

mv "${tmp}" "${file}"
trap - EXIT
