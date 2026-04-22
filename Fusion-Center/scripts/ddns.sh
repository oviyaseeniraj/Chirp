#!/bin/bash

# fake ddns, uploads ip to a github gist to store the current ip
# nodes call fetch_ddns.sh to update /etc/hosts to point base-station to the new ip

# Configuration
GIST_ID="f196ea8bc691933371b88ced2d097e13"
TOKEN="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"
FILENAME="ip_registry.txt"

# Get the current local IP (picks the first one starting with 10. or 192.)
LOCAL_IP=$(hostname -I | awk '{print $1}')

# Update the Gist via GitHub API
curl -L -X PATCH \
  -H "Authorization: token $TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  -d "{\"files\": {\"$FILENAME\": {\"content\": \"$LOCAL_IP\"}}}" \
  "https://api.github.com/gists/$GIST_ID"