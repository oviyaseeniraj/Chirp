# Step 3 Phase 0 Preflight Checklist (Node)

This checklist locks the pre-implementation contract before Phase 1 changes begin.

## Locked protocol contract

Server-side topic and payload contract is sourced from:
- `Fusion-Center/server_controller.py`

The Node trigger client must stay compatible with the following topics:
- `chirp/v1/group/<groupId>/capture/start` (subscribe)
- `chirp/v1/presence/<nodeId>` (publish, retained)
- `chirp/v1/group/<groupId>/capture/state/<nodeId>` (publish, retained)
- `chirp/v1/group/<groupId>/capture/ack/<nodeId>` (publish, non-retained)

Minimum start payload fields expected by Node:
- `schemaVersion`
- `groupId`
- `commandId`
- `startEpochMs`
- `targetNodeIds` (if present, node should verify membership)

## Runtime identity and configuration decisions

Step 3 uses runtime env values, not compile-time C networking constants:
- `MQTT_HOST`
- `MQTT_PORT`
- `NODE_ID`
- `GROUP_ID`
- `MQTT_CLIENT_ID`
- `MQTT_USERNAME`
- `MQTT_PASSWORD`
- `CHIRP_SCHEMA_VERSION`

Template values live in:
- `Node/.env.example`

## Scope boundary for Phase 1

Phase 1 is intentionally limited to trigger worker refactor:
- Convert `networked_trigger.c` from TCP master sync to absolute-time worker input.
- Preserve realtime scheduling and GPIO pulse logic.
- Do not implement MQTT logic yet.
- Do not change radar pipeline or Fusion-Center server behavior.

## Gate A definition (must pass before Phase 2)

1. Build succeeds for hardware trigger binaries.
2. Refactored worker starts pulsing when provided a future epoch.
3. `local_trigger` remains functional.
4. Phase 1 changes are committed independently from future MQTT client work.

## Recommended Phase 1 branch/commit discipline

- Keep one commit for Phase 1 only.
- Use commit message style such as:
  - `refactor trigger worker to use absolute start epoch`
