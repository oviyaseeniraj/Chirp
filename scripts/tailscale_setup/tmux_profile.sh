#!/usr/bin/env bash
set -euo pipefail

source .env

SESSION="logger"
CMD='curl -N http://:${GOTTY_PORT}'

tmux kill-session -t "$SESSION" 2>/dev/null || true

tmux new-session -d -s "$SESSION" "curl -N http:/${NODE1}/:${GOTTY_PORT}"
tmux split-window -h -t "$SESSION" "curl -N http:/${NODE2}/:${GOTTY_PORT}"
tmux split-window -v -t "$SESSION:0.0" "curl -N http:/${NODE3}/:${GOTTY_PORT}"
tmux split-window -v -t "$SESSION:0.1" "curl -N http:/${NODE4}/:${GOTTY_PORT}"

tmux select-layout -t "$SESSION" tiled
tmux attach -t "$SESSION"