#!/usr/bin/env bash
# Append a Chirp shell snippet to ~/.bashrc (idempotent) so Node/.env or broker/.env loads automatically.
#
# Usage:
#   ./scripts/chirp_install_shell_rc.sh orin /home/chirp/Chirp
#   ./scripts/chirp_install_shell_rc.sh xavier "$HOME/Documents/Chirp"
set -euo pipefail

ROLE="${1:?orin | xavier | laptop}"
REPO="${2:?path to Chirp clone}"

MARKER="# BEGIN CHIRP RUNBOOK"

if [[ ! -f "${REPO}/scripts/chirp_source_env.sh" ]]; then
  echo "Invalid CHIRP_REPO_ROOT: ${REPO}" >&2
  exit 1
fi

if grep -q "${MARKER}" "${HOME}/.bashrc" 2>/dev/null; then
  echo "~/.bashrc already contains Chirp snippet." >&2
  exit 0
fi

{
  echo ""
  echo "${MARKER}"
  echo "export CHIRP_REPO_ROOT=\"${REPO}\""
  echo "export CHIRP_ROLE=${ROLE}"
  echo "[[ -f \"\${CHIRP_REPO_ROOT}/scripts/chirp_source_env.sh\" ]] && source \"\${CHIRP_REPO_ROOT}/scripts/chirp_source_env.sh\""
  echo "# END CHIRP RUNBOOK"
} >>"${HOME}/.bashrc"

echo "Appended Chirp block to ~/.bashrc (CHIRP_REPO_ROOT=${REPO} CHIRP_ROLE=${ROLE}). Open a new shell or: source ~/.bashrc"
