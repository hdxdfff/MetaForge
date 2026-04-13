# Factory State

The persistent state for the local factory lives under `D:\codex\orchestrator-mvp\data`.

Important files:

- `context_kernel.json`: current compact control snapshot
- `hot_context.json`: active and failed task summary
- `project_summaries.json`: project memory
- `failure_patterns.json`: repeated failure buckets
- `escalation_inbox.json`: open operator items
- `core_agent_profile.json`: resident core-agent policy
- `tasks.json`: task ledger
- `identity_kernel.json`: live identity and consistency snapshot
- `METAFORGE_OS_SYSTEM_IDENTITY.json`: live system identity SSOT

Use the controller instead of editing these by hand unless you are intentionally repairing state.

Current operating reference:

- `D:\codex\METAFORGE_OS_HIGH_THROUGHPUT_BLUEPRINT.md`

The blueprint is the execution layer above the KPI and saturation policies. It defines queue names, task schema, WIP limits, verification levels, and rollout order.

The state model now also treats identity as a live kernel:

- system identity
- operator identity
- authority state
- runtime state
- memory integrity
- consistency findings

The live system identity SSOT is refreshed from the identity kernel and should be treated as the operator-facing authoritative identity record.
