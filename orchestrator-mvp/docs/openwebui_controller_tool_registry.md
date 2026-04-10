# MetaForge Controller API for Open WebUI

This is the bounded OpenAPI tool surface intended for Open WebUI.

## Server

- Docker compose mode:
  - OpenAPI source: `http://controller-api:8710/openapi.json`
  - Base URL: `http://controller-api:8710`
- Host mode:
  - OpenAPI source: `http://host.docker.internal:8710/openapi.json`
  - Base URL: `http://host.docker.internal:8710`
- Recommended Open WebUI mode: `Global Tool Server`
- Recommended scope: `admin_only`

## Tool Groups

### Read Only

Use these first to inspect runtime state without mutating anything.

- `GET /status`
- `GET /output/recent`
- `GET /health`
- `GET /runtime/summary`
- `GET /control/status`
- `GET /queue/status`
- `GET /tasks/pending`
- `GET /verification/status`
- `GET /artifacts/recent`

### Controlled Write

These mutate bounded controller state or task decisions.

- `POST /goal/activate`
- `POST /queue/pause`
- `POST /queue/resume`
- `POST /task/approve`
- `POST /task/reject`
- `POST /repair/schedule`

### Confirmation Gated

Only call these with explicit human confirmation.

- `POST /daemon/restart`
- `POST /release/promote`
- `POST /queue/clear-stale`
- `POST /runtime/rotate-epoch`

## Payload Convention

Send these common fields on every write call:

- `actor`: usually `webui`
- `source`: usually `open-webui`
- `reason`: optional human reason

Danger-gated endpoints also accept:

- `confirm`: `true` only after explicit confirmation

## Registration Notes

1. Add the server as an OpenAPI tool server in Open WebUI.
2. Keep the main orchestrator control plane separate.
3. Start with the read-only group to verify connectivity.
4. Move to controlled writes only after the read-only calls are stable.
5. Use confirmation-gated actions only from an admin workflow.
6. If Open WebUI runs in Docker on the same compose network, use `controller-api:8710`.
