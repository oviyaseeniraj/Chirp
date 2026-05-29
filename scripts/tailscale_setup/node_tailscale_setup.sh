#!/usr/bin/env bash

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (sudo)" 
   exit 1
fi

# Load .env and validate AUTH_KEY
if [[ ! -f auth_key ]]; then
  echo "Error: .env file not found. Please create one with AUTH_KEY defined."
  exit 1
fi

set -a
source auth_key
set +a

if [[ -z "${AUTH_KEY}" ]]; then
  echo "Error: AUTH_KEY is not defined or is empty in .env."
  exit 1
fi



curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --auth-key="${AUTH_KEY}"
systemctl enable --now tailscaled

