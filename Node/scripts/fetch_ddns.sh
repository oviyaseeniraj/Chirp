#!/bin/bash

# fake ddns, uses a github gist to store the current ip, and updates /etc/hosts to point base-station to the new ip

# view the logs at /var/log/script_startup.log
# add the following to cron (sudo crontab -e), adjust path as needed:
# @reboot /home/chirp/Chirp/Node/scripts/fetch_ddns.sh >> /var/log/script_startup.log 2>&1
# @hourly /home/chirp/Chirp/Node/scripts/fetch_ddns.sh >> /var/log/script_startup.log 2>&1


# Configuration
GIST_ID="f196ea8bc691933371b88ced2d097e13"
FILENAME="ip_registry.txt"

echo "Waiting for internet connection..."
until curl -s --head https://github.com > /dev/null; do
    sleep 2
done
echo "Internet is up!"

# 1. Fetch the raw file content directly from the Gist raw URL
# This avoids dependencies on JSON parsing tools like jq or python3
NEW_IP=$(curl -s -L "https://gist.github.com/chirp189/$GIST_ID/raw")

echo "Fetched IP from Gist: $NEW_IP"

if [[ $NEW_IP =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    # Update /etc/hosts: Remove old entry and append the new one [cite: 18, 50]
    sudo sed -i '/base-station/d' /etc/hosts
    echo "$NEW_IP base-station" | sudo tee -a /etc/hosts > /dev/null
    echo "Success: base-station now points to $NEW_IP" 
else
    echo "Error: Could not fetch raw IP. Response was: $NEW_IP"
    exit 1
fi