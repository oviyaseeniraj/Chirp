#!/usr/bin/env bash
set -euo pipefail

# ...existing code...
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd /tmp

OS_RAW=$(uname -s | tr '[:upper:]' '[:lower:]')
case "$OS_RAW" in
  linux) os="linux" ;;
  darwin|mac) os="darwin" ;;
  *) echo "Unsupported OS: $OS_RAW" >&2; exit 1 ;;
esac

ARCH_RAW=$(uname -m)
case "$ARCH_RAW" in
  x86_64|amd64) arch="amd64" ;;
  aarch64|arm64) arch="arm64" ;;
  armv7l|armv7|armhf) arch="arm" ;;
  i386|i686) arch="386" ;;
  *) echo "Unsupported arch: $ARCH_RAW" >&2; exit 1 ;;
esac

ASSET_NAME="gotty_${os}_${arch}.tar.gz"

repos=("yudai/gotty" "sorenisanerd/gotty")
download_url=""
for repo in "${repos[@]}"; do
  resp=$(curl -s "https://api.github.com/repos/${repo}/releases/latest")
  download_url=$(echo "$resp" | grep -oP '"browser_download_url":\s*"\K([^"]+)' \
    | grep -E "/${ASSET_NAME}$" || true)
  if [ -z "$download_url" ]; then
    download_url=$(echo "$resp" | grep -oP '"browser_download_url":\s*"\K([^"]+)' \
      | grep -E "${os}.*${arch}" | head -n1 || true)
  fi
  if [ -n "$download_url" ]; then
    break
  fi
done

if [ -z "$download_url" ]; then
  fallback_urls=(
    "https://github.com/sorenisanerd/gotty/releases/download/v1.8.0/gotty_v1.8.0_linux_arm64.tar.gz"
  )
  for u in "${fallback_urls[@]}"; do
    if curl -I -s --fail "$u" >/dev/null 2>&1; then
      download_url="$u"
      break
    fi
  done
fi

if [ -z "$download_url" ]; then
  echo "Could not find a release asset for ${ASSET_NAME}" >&2
  exit 1
fi

echo "Downloading ${download_url}"
wget -q --show-progress "$download_url" -O "$ASSET_NAME"
tar xzf "$ASSET_NAME"

sudo mv gotty /usr/local/bin
echo "Installed $(/usr/local/bin/gotty --version)"

# load environment values from repo .env (use script dir)
if [ -f "${SCRIPT_DIR}/.env" ]; then
  # shellcheck disable=SC1090
  source "${SCRIPT_DIR}/.env"
else
  echo "Warning: .env not found in ${SCRIPT_DIR}, continuing with defaults"
fi

# determine service user (can be overridden by GOTTY_USER env)
GOTTY_USER="${GOTTY_USER:-${SUDO_USER:-$(whoami)}}"
GOTTY_HOME="$(eval echo "~${GOTTY_USER}")"

# prepare /etc/gotty
sudo mkdir -p /etc/gotty
sudo chown "$GOTTY_USER":"$GOTTY_USER" /etc/gotty
sudo chmod 750 /etc/gotty

# ensure tailscale present
if ! command -v tailscale >/dev/null 2>&1; then
  echo "tailscale is required to generate the Tailnet cert" >&2
  exit 1
fi

# determine tailscale cert name (prefer explicit env)
TAILSCALE_CERT_NAME="${TAILSCALE_CERT_NAME:-}"

if [[ -z "${TAILSCALE_CERT_NAME}" ]]; then
  echo "Could not determine Tailscale DNS name. Set TAILSCALE_CERT_NAME explicitly." >&2
  exit 1
fi

# generate/obtain certs into /etc/gotty
sudo tailscale cert --cert-file /etc/gotty/gotty.crt --key-file /etc/gotty/gotty.key "${TAILSCALE_CERT_NAME}"
sudo chown "$GOTTY_USER":"$GOTTY_USER" /etc/gotty/gotty.crt /etc/gotty/gotty.key
sudo chmod 640 /etc/gotty/gotty.key
sudo chmod 644 /etc/gotty/gotty.crt

# write gotty config (absolute paths)
cat <<EOF | sudo tee /etc/gotty/gotty.conf >/dev/null
port = "${GOTTY_PORT:-8080}"

enable_tls = true
tls_crt_file = "/etc/gotty/gotty.crt"
tls_key_file = "/etc/gotty/gotty.key"

enable_basic_auth = true
credential = "${ADMIN:-admin}:${ADMIN_PASSWORD:-changeme}"

permit_write = true
random-url = true
EOF
sudo chown "$GOTTY_USER":"$GOTTY_USER" /etc/gotty/gotty.conf
sudo chmod 640 /etc/gotty/gotty.conf
# ...existing code...

# load environment values from repo .env (use script dir)
if [ -f "${SCRIPT_DIR}/.env" ]; then
  # shellcheck disable=SC1090
  source "${SCRIPT_DIR}/.env"
else
  echo "Warning: .env not found in ${SCRIPT_DIR}, continuing with defaults"
fi

# ...existing code...

# copy env for service (optional)
if [ -f "${SCRIPT_DIR}/.env" ]; then
  sudo cp "${SCRIPT_DIR}/.env" /etc/gotty/gotty_env
  sudo chown root:chirp /etc/gotty/gotty_env
  sudo chmod 640 /etc/gotty/gotty_env
fi

#enable the tmux profile
chmod +x ${SCRIPT_DIR}/tmux_profile.sh

# create global systemd service unit
sudo tee /etc/systemd/system/gotty.service >/dev/null <<'UNIT'
[Unit]
Description=gotty web terminal (tmux)
After=network-online.target tailscaled.service
Wants=network-online.target tailscaled.service

[Service]
User=chirp
Group=chirp
EnvironmentFile=/etc/gotty/gotty_env
WorkingDirectory=/home/chirp
ExecStart=/usr/local/bin/gotty --config /etc/gotty/gotty.conf /home/chirp/Documents/Chirp/scripts/tailscale_setup/tmux_profile.sh
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
UNIT

# substitute placeholders with actual user/home (atomic)
sudo sed -i "s|GOTTY_USER_PLACEHOLDER|${GOTTY_USER}|g" /etc/systemd/system/gotty.service
sudo sed -i "s|GOTTY_HOME_PLACEHOLDER|${GOTTY_HOME}|g" /etc/systemd/system/gotty.service

# enable and start service system-wide
sudo systemctl daemon-reload
sudo systemctl enable --now gotty.service

sudo systemctl status gotty.service --no-pager