# MetaForge OS State Model

This file defines the canonical state model for MetaForge OS.

## Purpose

The state model answers:

- what is the system doing now
- what is blocked
- what is healthy or unhealthy
- what needs operator or CEO-agent attention

## State domains

### 1. Identity-bound execution state

Minimum fields:

- `mode`
- `control_status`
- `active_task_count`
- `failed_task_count`
- `open_escalation_count`
- `active_workspaces`
- `execution_roots`

### 1b. Identity kernel state

Minimum fields:

- `system_identity`
- `operator_identity`
- `authority_state`
- `runtime_state`
- `memory_integrity`
- `consistency`
- `identity_revision`

The canonical system identity SSOT is `D:\codex\METAFORGE_OS_SYSTEM_IDENTITY.json`.
It is refreshed from the identity kernel and should mirror the current live operator-facing identity record.

### 2. Quality and autonomy state

Minimum fields:

- `autonomy_stage`
- `autonomy_score`
- `quality_status`
- `quality_score`
- `guard_status`

### 2b. Signal policy state

Signal policy is a control-plane classification layer. It separates residual signals into three buckets:

- `runtime_blockers`: the only signals allowed to trigger degrade, freeze, or recovery mode
- `maturity_signals`: dashboard and trend inputs only; they do not alter runtime state
- `release_gate_signals`: stage-gating and external release claims only; they do not alter daily execution

Typical examples:

- runtime blockers: daemon death, control-layer instability, verification hard block, critical state corruption
- maturity signals: quality attention, autonomy stage3, degraded AI test lanes
- release gate signals: stage4 confirmation, soak completion, benchmark readiness, AI tests fully green

The state model should preserve the distinction explicitly instead of collapsing all non-green signals into one bucket.

### 3. Delivery state

Minimum fields:

- `running_tasks`
- `delivery_targets`
- `verification_ready_count`
- `route_drift_count`
- `invalid_vdu_count`

### 4. Resource state

Minimum fields:

- `available_runtimes`
- `controller_available`
- `cheap_lane_available`
- `premium_dependency_level`

## Priority interpretation

The CEO layer should classify state into four priority bands:

- `green`: healthy and progressing
- `yellow`: attention needed but still operating
- `orange`: bounded degradation required
- `red`: operator intervention required

## MetaForge-specific state risks

The following risks must be surfaced explicitly:

- route drift outside target workspace
- premium dependency without fallback
- verification gaps
- persistent provider-only output
- stalled branch delivery
- identity drift between system, runtime, and control state
- stale memory cache or expired handoff leaking into live execution

## Current live-state sources

- `D:\codex\orchestrator-mvp\data\hot_context.json`
- `D:\codex\orchestrator-mvp\data\control_center_state.json`
- `D:\codex\orchestrator-mvp\data\autonomy_score.json`
- `D:\codex\orchestrator-mvp\data\quality_status.json`
- `D:\codex\orchestrator-mvp\data\escalation_inbox.json`
- `D:\codex\orchestrator-mvp\data\identity_kernel.json`
- `D:\codex\orchestrator-mvp\data\factory_daemon_state.json`
- `D:\codex\orchestrator-mvp\data\memory_objects.jsonl`

## Derived-state rule

The state model is allowed to derive judgments from raw files.
For example:

- if a bounded ToyOS task is running outside `D:\codex\generated\toy-os-demo`, count it as route drift
- if task outputs do not return to the target workspace, count them as invalid delivery

## CEO-agent rule

A CEO agent must not ask only whether tasks exist.
It must ask whether the current state still matches identity, scope, and delivery policy.

## Identity rule

The identity kernel is a live control-plane object, not a narrative description.
It must be refreshed from source state and checked for consistency before it is used for dispatch, handoff, or recovery decisions.
