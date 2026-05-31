#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_SRC="${SCRIPT_DIR}/chirp_pull_listener.service"
SERVICE_NAME="$(basename "${SERVICE_SRC}")"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}"
ENV_FILE="${SCRIPT_DIR}/.pull_listener_env"

SRC_DIR="$(cd "${SCRIPT_DIR}/../src" && pwd)"

if [[ ! -f "${SRC_DIR}/pull_listener.py" ]]; then
  echo "Missing ${SRC_DIR}/pull_listener.py" >&2
  exit 1
fi

if [[ ! -f "${SERVICE_SRC}" ]]; then
  echo "Missing ${SERVICE_SRC}" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}" >&2
  echo "Create it and define your PAT in PULL_TOKEN, along with the required settings:" >&2
  echo "  PULL_LISTENER_PORT" >&2
  echo "  PULL_REPO_DIR" >&2
  echo "  PULL_BRANCH" >&2
  echo "  PULL_SERVICE_NAME" >&2
  echo "  PULL_TOKEN" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

if [[ -z "${PULL_TOKEN:-}" ]]; then
  echo "PULL_TOKEN is not set in ${ENV_FILE}." >&2
  echo "Define it with your PAT and rerun this script." >&2
  exit 1
fi

sudo install -d -m 0755 "$(dirname "${ENV_FILE}")"
sudo chmod 600 "${ENV_FILE}"
sudo install -m 0644 "${SERVICE_SRC}" "${SERVICE_DST}"

sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"
sudo systemctl status "${SERVICE_NAME}" --no-pager