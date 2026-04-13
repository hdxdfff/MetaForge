# MetaForge Control Topology

This document is the canonical control-layer contract for the orchestrator MVP.

## Purpose

The system is split into five layers:

- `Core Controller`: the only state source and the owner of policy, queue, memory, verification, audit, and artifact ledger
- `Appsmith`: control surface for dashboards, approvals, and manual intervention
- `n8n`: event-driven automation and external-system integration
- `Dify`: AI workflow orchestration for business-facing flows
- `OpenHands`: execution layer for code, tests, patches, and evidence

`Open WebUI` is the human entry surface and is now run as a dedicated control-entry stack on `http://127.0.0.1:3001`.

## Controller Contract

The controller API exposes the machine-readable topology at:

- `GET /topology`
- `GET /integrations/status`

The same API also exposes the bounded operational surface used by control surfaces:

- Read only: `GET /health`, `GET /runtime/summary`, `GET /control/status`, `GET /queue/status`, `GET /tasks/pending`, `GET /verification/status`, `GET /artifacts/recent`
- Controlled write: `POST /goal/activate`, `POST /queue/pause`, `POST /queue/resume`, `POST /task/approve`, `POST /task/reject`, `POST /repair/schedule`
- Confirmation gated: `POST /daemon/restart`, `POST /release/promote`, `POST /queue/clear-stale`, `POST /runtime/rotate-epoch`

## Boundary Rules

- `Core Controller` is the SSOT.
- `Appsmith` may observe and approve, but it does not own state.
- `n8n` handles automation, not governance.
- `Dify` handles workflows, not release decisions.
- `OpenHands` executes work and returns artifacts, not policy.
- `Open WebUI` is the human entry surface and must route through the controller API rather than direct state files.
- Every execution path must end in evidence captured by the controller ledger.

The instance bindings are configured through environment variables documented in `docs/external_instances.md`.

## Recommended Sequence

1. Human intent enters through `Open WebUI`.
2. `Core Controller` normalizes the request and records state.
3. `Appsmith` provides visibility and manual intervention.
4. `n8n` or `Dify` fans out automation and workflow steps.
5. `OpenHands` or another execution adapter performs bounded work.
6. `Core Controller` validates the evidence and updates the ledger.
