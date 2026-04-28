#!/usr/bin/env bash
# Guess MQTT broker (Xavier) IPv4 from chrony — Orins are often NTP-synced to that same host.
# Prints one address or exits 1.
set -euo pipefail

_is_ipv4() {
  [[ "${1}" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]
}

chrony_files=()
if [[ -f /etc/chrony/chrony.conf ]]; then
  chrony_files+=(/etc/chrony/chrony.conf)
fi
if compgen -G '/etc/chrony/sources.d/*.conf' >/dev/null; then
  for f in /etc/chrony/sources.d/*.conf; do
    chrony_files+=("${f}")
  done
fi

for cf in "${chrony_files[@]}"; do
  while read -r _ word _; do
    [[ -z "${word}" ]] && continue
    h="${word%,}"
    if _is_ipv4 "${h}"; then
      printf '%s\n' "${h}"
      exit 0
    fi
  done < <(grep -E '^[[:space:]]*(server|peer)[[:space:]]' "${cf}" 2>/dev/null | grep -v '^[[:space:]]*#' || true)
done

if command -v chronyc >/dev/null 2>&1; then
  ip="$(chronyc -n sources 2>/dev/null | awk '/^\^\*/ {print $2; exit}')"
  if [[ -n "${ip}" ]] && _is_ipv4 "${ip}"; then
    printf '%s\n' "${ip}"
    exit 0
  fi
fi

exit 1
