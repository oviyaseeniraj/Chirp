#!/usr/bin/env bash
set -euo pipefail

if [[ -f /etc/gotty/gotty_env ]]; then
  # shellcheck disable=SC1091
  set -a
  source /etc/gotty/gotty_env
  set +a
else
  echo "Missing /etc/gotty/gotty_env" >&2
  exit 1
fi

SESSION="web-interface"
LOGGER_PORT="${LOGGER_PORT:-5003}"

tmux kill-session -t "$SESSION" 2>/dev/null || true

tmux new-session -d -s "$SESSION" -n logs "curl -N http://${NODE1}:${LOGGER_PORT}"
tmux split-window -h -t "$SESSION:0" "curl -N http://${NODE2}:${LOGGER_PORT}"
tmux split-window -v -t "$SESSION:0.0" "curl -N http://${NODE3}:${LOGGER_PORT}"
tmux split-window -v -t "$SESSION:0.1" "curl -N http://${NODE4}:${LOGGER_PORT}"

tmux select-layout -t "$SESSION:0" tiled

tmux new-window -t "$SESSION" -n "command prompt" "bash"
tmux select-window -t "$SESSION:0"

tmux attach -t "$SESSION"