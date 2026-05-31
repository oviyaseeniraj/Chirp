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

# First window: read-only instructions
tmux new-session -d -s "$SESSION" -n "instructions" "bash -lc 'clear; cat <<\"EOF\"
Web interface navigation:
- Ctrl-b n : next window
- Ctrl-b p : previous window
- Ctrl-b 0-9 : jump to a window
- Ctrl-b d : detach from tmux
- Ctrl-b ? : show key bindings

Pane navigation:
- Ctrl-b arrow keys : move between panes
- Ctrl-b o : cycle through panes
- Ctrl-b q : show pane numbers
- Ctrl-b { : swap pane with previous
- Ctrl-b } : swap pane with next

Windows:
1. instructions
2. logs
3. command prompt
EOF
sleep infinity'"

# Second window: 4 panes, one per node
# ...existing code...

# Second window: 4 panes, one per node
tmux new-window -t "$SESSION" -n "logs"
tmux send-keys -t "$SESSION:1.0" "ssh -t ${NODE1} 'sudo journalctl -u chirp-launcher -f'" C-m
tmux split-window -h -t "$SESSION:1.0" "ssh -t ${NODE2} 'sudo journalctl -u chirp-launcher -f'"
tmux split-window -v -t "$SESSION:1.0" "ssh -t ${NODE3} 'sudo journalctl -u chirp-launcher -f'"
tmux split-window -v -t "$SESSION:1.1" "ssh -t ${NODE4} 'sudo journalctl -u chirp-launcher -f'"
tmux select-layout -t "$SESSION:1" tiled

# ...existing code...

# Third window: shell prompt
tmux new-window -t "$SESSION" -n "command prompt" "bash"

# Start on the instructions window
tmux select-window -t "$SESSION:0"

tmux attach -t "$SESSION"