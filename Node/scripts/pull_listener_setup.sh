#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_SRC="${SCRIPT_DIR}/chirp_pull_listener.service"
SERVICE_NAME="$(basename "${SERVICE_SRC}")"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}"
ENV_TEMPLATE="${SCRIPT_DIR}/.pull_listener_env"
ENV_FILE="/etc/chirp-pull-listener.env"

# Defaults (override by exporting before running)
PULL_LISTENER_PORT="${PULL_LISTENER_PORT:-5055}"
PULL_REPO_DIR="${PULL_REPO_DIR:-/home/chirp/Chirp}"
PULL_BRANCH="${PULL_BRANCH:-main}"
PULL_SERVICE_NAME="${PULL_SERVICE_NAME:-chirp-launcher.service}"
PULL_TOKEN="${PULL_TOKEN:-}"

SRC_DIR="$(cd "${SCRIPT_DIR}/../src" && pwd)"

if [[ ! -f "${SRC_DIR}/pull_listener.py" ]]; then
  echo "Missing ${SRC_DIR}/pull_listener.py" >&2
  exit 1
fi

if [[ ! -f "${SERVICE_SRC}" ]]; then
  echo "Missing ${SERVICE_SRC}" >&2
  exit 1
fi



# Resolve EnvironmentFile path from service (supports optional '-' prefix)
ENV_FILE_LINE="$(grep -E '^[[:space:]]*EnvironmentFile=' "${SERVICE_SRC}" | head -n1 || true)"
if [[ -n "${ENV_FILE_LINE}" ]]; then
  ENV_FILE="${ENV_FILE_LINE#*=}"
  ENV_FILE="${ENV_FILE#-}"
else
  ENV_FILE="/etc/chirp-pull-listener.env"
fi

# Ensure env directory exists before writing
sudo install -d -m 0755 "$(dirname "${ENV_FILE}")"

# Copy template env file if present, otherwise generate defaults
if [[ -f "${ENV_TEMPLATE}" ]]; then
  sudo install -m 600 "${ENV_TEMPLATE}" "${ENV_FILE}"
else
  sudo tee "${ENV_FILE}" >/dev/null <<EOF
PULL_LISTENER_PORT=${PULL_LISTENER_PORT}
PULL_REPO_DIR=${PULL_REPO_DIR}
PULL_BRANCH=${PULL_BRANCH}
PULL_SERVICE_NAME=${PULL_SERVICE_NAME}
PULL_TOKEN=${PULL_TOKEN}
EOF
  sudo chmod 600 "${ENV_FILE}"
fi

# Enable + start
sudo install -m 0644 "${SERVICE_SRC}" "${SERVICE_DST}"

sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"
sudo systemctl status "${SERVICE_NAME}" --no-pager