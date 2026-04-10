# Open WebUI First Run

This is the minimal operator checklist for bringing Open WebUI online as the MetaForge control entry.

## 1. Prepare

1. Make sure `WEBUI_SECRET_KEY` is set in `.env` to a long random value.
2. Confirm the controller API is configured in the control-entry compose stack.
3. Keep `docs/openwebui_controller_tool_registry.json` open for tool registration.
4. Reuse the existing `CODING_PLAN_*` values from `D:\codex\orchestrator-mvp\.env` for the model connection.

## 2. Start

Run the combined control-entry stack:

```powershell
powershell -ExecutionPolicy Bypass -File .\run-control-entry.ps1
```

Expected services:

- Open WebUI: `http://localhost:3001`
- Controller API: `http://localhost:8710`
- Model gateway: `http://model-gateway:8711`

## 3. Verify

Run the entry smoke check:

```powershell
powershell -ExecutionPolicy Bypass -File .\run-control-entry-smoke.ps1
```

The smoke check should confirm:

- Controller topology is reachable at `/topology`
- Open WebUI responds on port `3001`
- Open WebUI is prewired to the existing OpenCode-compatible coding plan endpoint
- Default chat models are `minimax-m2.5` and `kimi-k2.5`
- The derived model policy snapshot is `docs/openwebui_model_policy.json`
- Open WebUI talks to the local model gateway on `http://model-gateway:8711`

## 4. Register Tools

In Open WebUI, register the Controller API as a `Global Tool Server`.

Use one of these depending on your runtime layout:

- Same Docker network: `http://controller-api:8710/openapi.json`
- Host reachable from Docker: `http://host.docker.internal:8710/openapi.json`

Use the registry file for the exact tool groups:

- `docs/openwebui_controller_tool_registry.json`

## 5. First Operator Loop

1. Open Open WebUI.
2. Confirm the controller tools are visible.
3. Call a read-only tool first, such as `GET /status` or `GET /health`.
4. Verify the runtime summary and queue state.
5. Only then use write tools like `POST /queue/pause` or `POST /goal/activate`.
