#!/usr/bin/env bash
# Print one routable IPv4 for this machine (for MQTT_HOST on the broker host, etc.).
#
# Override: CHIRP_LAN_IP_OVERRIDE=169.231.46.13 ./chirp_detect_lan_ipv4.sh
set -euo pipefail

if [[ -n "${CHIRP_LAN_IP_OVERRIDE:-}" ]]; then
  printf '%s\n' "${CHIRP_LAN_IP_OVERRIDE}"
  exit 0
fi

ip_out=""
if ip -4 route get 8.8.8.8 >/dev/null 2>&1; then
  ip_out="$(ip -4 route get 8.8.8.8 2>/dev/null | awk '{ for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit } }')"
fi

if [[ -n "${ip_out}" ]]; then
  printf '%s\n' "${ip_out}"
  exit 0
fi

for iface in eth0 end0 wlan0 wlP3p1s0 enP8p1s0; do
  if ip -4 -o addr show "${iface}" >/dev/null 2>&1; then
    ip_out="$(ip -4 -o addr show "${iface}" 2>/dev/null | awk '{ print $4 }' | cut -d/ -f1 | head -1)"
    if [[ -n "${ip_out}" ]]; then
      printf '%s\n' "${ip_out}"
      exit 0
    fi
  fi
done

echo "chirp_detect_lan_ipv4: could not determine IPv4 (set CHIRP_LAN_IP_OVERRIDE)" >&2
exit 1
