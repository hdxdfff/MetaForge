# External Instance Bindings

This repository can connect the control plane to real Open WebUI, Appsmith, n8n, Dify, and OpenHands instances.

## Environment Variables

- `ORCH_OPENWEBUI_BASE_URL`: base URL for Open WebUI, default `http://localhost:3001`
- `ORCH_OPENWEBUI_STATUS_URL`: optional explicit health or status URL for Open WebUI
- `ORCH_OPENWEBUI_API_KEY`: optional auth marker for Open WebUI
- `ORCH_APPSMITH_BASE_URL`: base URL for Appsmith, default `http://localhost:8080`
- `ORCH_APPSMITH_STATUS_URL`: optional explicit health or status URL for Appsmith
- `ORCH_APPSMITH_API_KEY`: optional auth marker for Appsmith
- `ORCH_N8N_BASE_URL`: base URL for n8n, default `http://localhost:5678`
- `ORCH_N8N_STATUS_URL`: optional explicit health or status URL for n8n
- `ORCH_N8N_API_KEY`: optional auth marker for n8n
- `ORCH_DIFY_BASE_URL`: base URL for Dify, default `http://localhost:8088`
- `ORCH_DIFY_STATUS_URL`: optional explicit health or status URL for Dify
- `ORCH_DIFY_API_KEY`: optional auth marker for Dify
- `ORCH_OPENHANDS_BASE_URL`: optional OpenHands base URL if the instance is exposed over HTTP
- `ORCH_OPENHANDS_STATUS_URL`: optional explicit health or status URL for OpenHands
- `ORCH_OPENHANDS_API_KEY`: optional auth marker for OpenHands
- `ORCH_OPENHANDS_EXECUTOR_ID`: executor ID to bind to the OpenHands adapter
- `ORCH_INTEGRATION_PROBE_TIMEOUT_SECONDS`: probe timeout for HTTP integrations

## Runtime Surface

- `GET /topology` lists the configured bindings.
- `GET /integrations/status` probes the live status of each configured binding.

## Notes

- `Open WebUI` is the live human entry surface in this workspace and is exposed on `http://localhost:3001`.
- `OpenHands` already exists as an executor in the repository; the binding here only makes its instance explicit in the control plane.
- `Appsmith`, `n8n`, and `Dify` are treated as external HTTP integrations, with the exact health URL supplied by configuration when the default base URL is not sufficient.
