# Open WebUI Control Entry

Open WebUI is the human entry surface for MetaForge when you want chat-driven control and review.
It is wired to the existing `CODING_PLAN_*` OpenCode configuration through a local model gateway, so the same OpenAI-compatible provider can be used for chat and operator tasks while exposing only a small allowlist.
The default and pinned chat models are `minimax-m2.5` and `kimi-k2.5`.
The derived policy snapshot is kept in `docs/openwebui_model_policy.json`.
The local model gateway is the only model source Open WebUI should query.
For system questions, prefer the controller `GET /status` tool first; it is the shortest path to a 24-hour output summary.

## Components

- `Open WebUI`: operator chat surface and tool caller
- `Controller API`: bounded OpenAPI control surface and state SSOT
- `Core Controller`: the runtime state and evidence owner behind the API

## Start

1. Ensure `WEBUI_SECRET_KEY` is set in `.env`.
2. Start the control-entry stack:

```powershell
powershell -ExecutionPolicy Bypass -File .\run-control-entry.ps1
```

3. Open WebUI should be available at:

- `http://localhost:3001`

4. The controller API should be available at:

- `http://localhost:8710`

## Tool Registration

Register the controller API as a Global Tool Server in Open WebUI.

- Docker compose mode:
  - OpenAPI source: `http://controller-api:8710/openapi.json`
  - Base URL: `http://controller-api:8710`
- Host mode:
  - OpenAPI source: `http://host.docker.internal:8710/openapi.json`
  - Base URL: `http://host.docker.internal:8710`

The tool registry lives in:

- `docs/openwebui_controller_tool_registry.json`
- `docs/openwebui_controller_tool_registry.md`

## Operational Rule

Open WebUI is the entry point.
The Controller API remains the only state source and mutation authority.
The local model gateway is the only model source that Open WebUI should use.
