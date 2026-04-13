# MetaForge Provider Gateway

## Landed controls

- Provider requests now pass through `app/provider_gateway.py`.
- Each provider route is scored by recent latency and consecutive failures.
- Repeated failures open a short circuit instead of hammering the same route.
- Route candidates can vary by `base_url` and `proxy`.
- Operator state is visible at `/api/network/state` and `/api/network/provider-routes`.

## Config knobs

- `OPENAI_BASE_URL_CANDIDATES`
- `OPENAI_PROXY_CANDIDATES`
- `CHEAP_LLM_BASE_URL_CANDIDATES`
- `CHEAP_LLM_PROXY_CANDIDATES`
- `ORCH_PROVIDER_ROUTE_MAX_ATTEMPTS`
- `ORCH_PROVIDER_ROUTE_BACKOFF_SECONDS`
- `ORCH_PROVIDER_CIRCUIT_FAILURE_THRESHOLD`
- `ORCH_PROVIDER_CIRCUIT_COOLDOWN_SECONDS`

## Validation target

- `python -m compileall app tools`
- `powershell -ExecutionPolicy Bypass -File D:\codex\factoryctl.ps1 daemon-status`
- `powershell -ExecutionPolicy Bypass -File D:\codex\factoryctl.ps1 control-layer-status`
- `powershell -ExecutionPolicy Bypass -File D:\codex\factoryctl.ps1 engineering-os-status`
