#!/usr/bin/env bash
# Source MQTT-related variables from Chirp .env files (add to ~/.bashrc).
#
# One-time per machine in ~/.bashrc:
#   export CHIRP_REPO_ROOT="$HOME/Documents/Chirp"
#   export CHIRP_ROLE=xavier    # or: orin | laptop
#   source "$CHIRP_REPO_ROOT/scripts/chirp_source_env.sh"
#
# CHIRP_ROLE:
#   xavier  — Fusion-Center/.env (or MQTT-Broker/.env)
#   orin    — Node/.env
#   laptop  — Fusion-Center/.env (or Laptop/.env, or MQTT-Broker/.env)
# Do not use `set -e` here — this file is sourced from interactive shells.

_chirp_source_env_fatal() { echo "chirp_source_env.sh: $*" >&2; return 1; }

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "chirp_source_env.sh: must be sourced: source ${BASH_SOURCE[0]}" >&2
  exit 1
fi

if [[ -z "${CHIRP_REPO_ROOT:-}" ]]; then
  _chirp_source_env_fatal "set CHIRP_REPO_ROOT to your Chirp clone path"
  return 1 2>/dev/null || exit 1
fi

role="${CHIRP_ROLE:-}"
if [[ -z "${role}" ]]; then
  _chirp_source_env_fatal "set CHIRP_ROLE to xavier, orin, or laptop"
  return 1 2>/dev/null || exit 1
fi

fc_env="${CHIRP_REPO_ROOT}/Fusion-Center/.env"
broker_env="${CHIRP_REPO_ROOT}/Fusion-Center/MQTT-Broker/.env"
laptop_env="${CHIRP_REPO_ROOT}/Fusion-Center/Laptop/.env"
node_env="${CHIRP_REPO_ROOT}/Node/.env"

set -a
case "${role}" in
  xavier)
    if [[ -f "${fc_env}" ]]; then
      # shellcheck disable=SC1090
      source "${fc_env}"
    elif [[ -f "${broker_env}" ]]; then
      # shellcheck disable=SC1090
      source "${broker_env}"
    else
      _chirp_source_env_fatal "missing ${fc_env} and ${broker_env}"
      return 1
    fi
    ;;
  orin)
    [[ -f "${node_env}" ]] || { _chirp_source_env_fatal "missing ${node_env} — run scripts/chirp_bootstrap_node_env.sh"; return 1; }
    # shellcheck disable=SC1090
    source "${node_env}"
    ;;
  laptop)
    if [[ -f "${fc_env}" ]]; then
      # shellcheck disable=SC1090
      source "${fc_env}"
    elif [[ -f "${broker_env}" ]]; then
      # shellcheck disable=SC1090
      source "${broker_env}"
    elif [[ -f "${laptop_env}" ]]; then
      # shellcheck disable=SC1090
      source "${laptop_env}"
    else
      _chirp_source_env_fatal "missing ${fc_env}, ${broker_env}, and ${laptop_env} — create Fusion-Center/.env or run scripts/chirp_runbook_laptop_env.sh"
      return 1
    fi
    export MQTT_LAPTOP_USER="${MQTT_LAPTOP_USER:-laptop-control}"
    export DASHBOARD_PORT="${DASHBOARD_PORT:-5002}"
    ;;
  *)
    _chirp_source_env_fatal "CHIRP_ROLE must be xavier, orin, or laptop (got ${role})"
    return 1
    ;;
esac
set +a
