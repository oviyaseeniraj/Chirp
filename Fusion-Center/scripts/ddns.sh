#!/bin/bash

# fake ddns, uploads ip to a github gist to store the current ip
# nodes call fetch_ddns.sh to update /etc/hosts to point base-station to the new ip
# view the logs at /var/log/script_startup.log
# add the following to cron (sudo crontab -e), adjust path as needed:
# @reboot /home/chirp/Documents/Chirp/Fusion-Center/scripts/ddns.sh >> /var/log/script_startup.log 2>&1
# */5 * * * * /home/chirp/Documents/Chirp/Fusion-Center/scripts/ddns.sh >> /var/log/script_startup.log 2>&1


# Configuration
# adjust to match whatever path
source /home/chirp/Documents/Chirp/.env
GIST_ID="f196ea8bc691933371b88ced2d097e13"
FILENAME="ip_registry.txt"

echo "Waiting for internet connection..."
until curl -s --head https://github.com > /dev/null; do
    sleep 2
done
echo "Internet is up!"

# Get the current local IP (picks the first one starting with 10. or 192.)
LOCAL_IP=$(hostname -I | awk '{print $1}')

# 1. Fetch the raw file content directly from the Gist raw URL
NEW_IP=$(curl -s -L "https://gist.github.com/chirp189/$GIST_ID/raw")

# Update the Gist via GitHub API
if [ "$NEW_IP" != "$LOCAL_IP" ]; then
# echo "Updating Gist with new IP: $LOCAL_IP"
curl -L -X PATCH \
  -H "Authorization: token $TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  -d "{\"files\": {\"$FILENAME\": {\"content\": \"$LOCAL_IP\"}}}" \
  "https://api.github.com/gists/$GIST_ID"
else
echo "IP is unchanged: $LOCAL_IP"
fi