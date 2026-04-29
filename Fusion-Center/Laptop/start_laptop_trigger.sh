#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FUSION_CENTER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
FC_ENV="${FUSION_CENTER_DIR}/.env"
BROKER_ENV_FILE="${FUSION_CENTER_DIR}/MQTT-Broker/.env"
LAPTOP_ENV_FILE="${SCRIPT_DIR}/.env"

if [[ -f "${FC_ENV}" ]]; then
  # shellcheck disable=SC1090
  source "${FC_ENV}"
elif [[ -f "${BROKER_ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${BROKER_ENV_FILE}"
elif [[ -f "${LAPTOP_ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${LAPTOP_ENV_FILE}"
else
  echo "Missing ${FC_ENV}, ${BROKER_ENV_FILE}, or ${LAPTOP_ENV_FILE}."
  echo "On a full clone run: Chirp/scripts/chirp_runbook_laptop_env.sh (after Fusion-Center/.env exists on the Xavier)."
  exit 1
fi

export MQTT_HOST="${MQTT_HOST:-127.0.0.1}"
export MQTT_PORT="${MQTT_PORT:-1883}"
export MQTT_LAPTOP_USER="${MQTT_LAPTOP_USER:-laptop-control}"
export MQTT_LAPTOP_PASS="${MQTT_LAPTOP_PASS:-}"

if [[ -z "${MQTT_LAPTOP_PASS:-}" ]]; then
  echo "Missing MQTT password (MQTT_LAPTOP_PASS)."
  echo "Set it in environment, ${FC_ENV}, or ${BROKER_ENV_FILE}."
  exit 1
fi

MQTT_TAP_PIDS=()
cleanup_mqtt_taps() {
  if [[ "${#MQTT_TAP_PIDS[@]}" -gt 0 ]]; then
    kill "${MQTT_TAP_PIDS[@]}" 2>/dev/null || true
    MQTT_TAP_PIDS=()
  fi
}
trap cleanup_mqtt_taps EXIT

ORIG_ARGS=("$@")

MONITOR_CALIB_STREAM=0
STRIP_STREAM_OPT=()
for arg in "${ORIG_ARGS[@]}"; do
  case "$arg" in
    --calibration)
      MONITOR_CALIB_STREAM=1
      STRIP_STREAM_OPT+=("$arg")
      ;;
    --no-calibration-stream)
      MONITOR_CALIB_STREAM=0
      ;;
    *)
      STRIP_STREAM_OPT+=("$arg")
      ;;
  esac
done

GROUP_ID_FOR_TOPICS="${GROUP_ID:-default}"
for ((i = 0; i < ${#ORIG_ARGS[@]}; i++)); do
  if [[ "${ORIG_ARGS[i]}" == "--group-id" && $((i + 1)) -lt ${#ORIG_ARGS[@]} ]]; then
    GROUP_ID_FOR_TOPICS="${ORIG_ARGS[i + 1]}"
    break
  fi
done

TOPIC_PREFIX="chirp/v1"

if [[ "${MONITOR_CALIB_STREAM}" -eq 1 ]]; then
  if ! command -v mosquitto_sub >/dev/null 2>&1; then
    echo "Note: install Mosquitto clients (mosquitto_sub) to see calibration MQTT traffic; continuing without tap."
  else
    echo "Calibration MQTT tap (group=${GROUP_ID_FOR_TOPICS}, broker=${MQTT_HOST}:${MQTT_PORT})"
    # ACL: laptop-control may read start/result + calibration/result only.
    #      server-xavier may read calibration/frame/+ and calibration/done/+ (not result).
    mosquitto_sub -h "${MQTT_HOST}" -p "${MQTT_PORT}" \
      -u "${MQTT_LAPTOP_USER}" -P "${MQTT_LAPTOP_PASS}" \
      -t "${TOPIC_PREFIX}/server/start/result" \
      -t "${TOPIC_PREFIX}/group/${GROUP_ID_FOR_TOPICS}/calibration/result" \
      -v 2>/dev/null | awk '{ print "[mqtt laptop] " $0; fflush() }' &
    MQTT_TAP_PIDS+=($!)

    SERVER_USER="${MQTT_SERVER_USER:-${MQTT_USERNAME:-server-xavier}}"
    SERVER_PASS="${MQTT_SERVER_PASS:-${MQTT_PASSWORD:-}}"
    if [[ -n "${SERVER_PASS}" ]]; then
      mosquitto_sub -h "${MQTT_HOST}" -p "${MQTT_PORT}" \
        -u "${SERVER_USER}" -P "${SERVER_PASS}" \
        -t "${TOPIC_PREFIX}/group/${GROUP_ID_FOR_TOPICS}/calibration/frame/+" \
        -t "${TOPIC_PREFIX}/group/${GROUP_ID_FOR_TOPICS}/calibration/done/+" \
        -v 2>/dev/null | awk '{ print "[mqtt server] " $0; fflush() }' &
      MQTT_TAP_PIDS+=($!)
    else
      echo "Note: set MQTT_SERVER_PASS or MQTT_PASSWORD in ${FC_ENV} to tap calibration/frame and calibration/done (laptop ACL cannot subscribe to those)."
    fi
    echo ""
  fi
fi

python3 "${SCRIPT_DIR}/laptop_trigger_client.py" "${STRIP_STREAM_OPT[@]}"
