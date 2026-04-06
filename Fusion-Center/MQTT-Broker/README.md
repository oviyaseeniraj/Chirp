# MQTT Broker Deployment (Xavier)

This directory contains part 1 of the MQTT trigger rollout: broker deployment and policy on the server node.

## What is included

- `docker-compose.yaml`: Mosquitto container deployment.
- `mosquitto.conf`: persistence, auth, queue limits, logging.
- `acl`: topic-level authorization for laptop/server/radar roles.
- `.env.example`: credential template.
- `bootstrap_passwords.sh`: creates `passwords` file from `.env`.
- `start_broker.sh`: starts broker with Docker Compose.
- `clear_retained.sh`: clears retained presence/state topics for one node.

## Quick start on Xavier

1. Install prerequisites:
   - Docker + Docker Compose plugin; [follow the install steps for Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
   - Mosquitto CLI tools (`mosquitto_pub`, optional `mosquitto_passwd`)
2. Create credentials:
   - `cp .env.example .env`
   - Edit `.env` with strong passwords.
3. Build password database:
   - `chmod +x bootstrap_passwords.sh start_broker.sh clear_retained.sh`
   - `./bootstrap_passwords.sh`
4. Start broker:
   - `./start_broker.sh`
5. Validate:
   - `docker compose -f docker-compose.yaml ps`
   - `docker compose -f docker-compose.yaml logs --tail=50`

## Topic contract and auth mapping

- Laptop (`laptop-control`)
  - Publish: `chirp/v1/server/start/request`
  - Read: `chirp/v1/server/start/result`
- Server (`server-xavier`)
  - Read: `chirp/v1/server/start/request`, `chirp/v1/presence/+`, ack/state topics
  - Publish: start/resync/result topics
- Radar nodes (`username == nodeId`)
  - Publish only:
    - `chirp/v1/presence/<nodeId>` (retained)
    - `chirp/v1/group/<groupId>/capture/ack/<nodeId>`
    - `chirp/v1/group/<groupId>/capture/state/<nodeId>` (retained)
  - Subscribe only:
    - `chirp/v1/group/<groupId>/capture/start`
    - `chirp/v1/group/<groupId>/capture/resync`

## Last Will conventions

Each MQTT client should set a will message when connecting:

- Topic: `chirp/v1/presence/<nodeId>`
- Retain: `true`
- QoS: `1`
- Payload (example):
  - `{"schemaVersion":1,"nodeId":"radar-orin-01","status":"offline","timestampMs":1700000000000}`

On successful connect, clients should immediately publish retained `status=online` on the same topic.

Server client should also set a will:

- Topic: `chirp/v1/server/status`
- Retain: `true`
- QoS: `1`
- Payload includes `status=offline`.

## Retained message policy

- Keep retained messages only for:
  - presence (`chirp/v1/presence/<nodeId>`)
  - latest node state (`chirp/v1/group/<groupId>/capture/state/<nodeId>`)
- Do not retain command topics (`.../capture/start`, `.../capture/resync`) to avoid stale starts.
- Use `clear_retained.sh <groupId> <nodeId>` when decommissioning/relabeling a node.

## Notes

- TLS (`8883`) is intentionally left for a later hardening step; current deployment is auth-only on `1883`.
- Use stable client IDs:
  - `server-xavier`
  - `laptop-control`
  - `radar-<serial-or-nodeId>`
