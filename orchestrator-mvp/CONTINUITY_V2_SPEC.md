# Continuity V2 Spec

## Purpose

Continuity v2 defines service continuity as the conjunction of runtime continuity, state continuity, control-semantic continuity, and evidence continuity.
A preserved runtime epoch alone is insufficient to claim full service-semantic soak unless state, control compatibility, and durable evidence also remain preserved.

## Model

The continuity model has four fact layers:

- `runtime_continuity`: `preserved | degraded | broken | unknown`
- `state_continuity`: `preserved | degraded | broken | unknown`
- `control_semantic_continuity`: `preserved | compatible_changed | incompatible | unknown`
- `evidence_continuity`: `preserved | degraded | broken | unknown`

And two aggregate layers:

- `epoch_health`: `healthy | degraded | broken`
- `claim_scope`: `runtime_only | runtime_plus_state | full_service_semantic | unclaimable`

## Compatibility

`continuity_mode` remains as a backward-compatible coarse field:

- `preserved` when runtime continuity is preserved and no hard break is detected
- `new` when a hard break is detected or a new epoch is created

New consumers must prefer the v2 fields over `continuity_mode`.

## Break Reasons

Hard break reasons are used when the current epoch can no longer preserve service continuity:

- Runtime: `cold_boot`, `manual_restart`, `unexpected_process_restart`, `watchdog_recovery`, `tick_gap_exceeded`, `heartbeat_stall`
- State: `manual_state_reset`, `state_loss_detected`, `queue_loss_detected`, `inflight_loss_detected`, `ledger_regression_detected`, `runtime_state_truncated`, `artifact_registry_regression`, `verification_state_regression`
- Control semantics: `incompatible_upgrade`, `control_contract_changed`, `policy_semantics_changed`, `tool_policy_changed_incompatible`, `router_behavior_changed`, `worker_contract_changed`
- Evidence: `epoch_write_failed`, `milestone_commit_failed`, `evidence_sink_unavailable`, `telemetry_gap_detected`, `durable_checkpoint_missing`, `ssot_stale`, `evidence_file_corrupted`
- Uncertainty: `continuity_unknown_due_to_missing_evidence`, `continuity_unknown_due_to_partial_state`, `continuity_unknown_due_to_schema_mismatch`

## Risk Reasons

Risk reasons do not break the epoch by themselves. They degrade confidence or claim scope:

- `state_write_permission_denied`
- `ssot_stale`
- `telemetry_gap_detected`
- `durable_checkpoint_missing`

## Current Minimal Implementation

This repository currently implements a minimal v2 subset in `tools/factory_daemon.py`:

- Runtime continuity preserves the epoch when the previous epoch was active and `last_alive_at` is within a 120s recovery window.
- PID changes inside that window increment `restart_count_within_epoch` and keep the same `epoch_id`.
- Evidence continuity degrades when recent daemon log tails contain `PermissionError` on critical state writes.
- Evidence continuity breaks when permission-denied writes exceed the configured threshold or durable checkpoint freshness exceeds the configured stale threshold.
- State continuity currently uses best-effort digests for task queue, inflight status, artifact registry, verification state, and milestone ledger.
- Control semantic continuity is currently a lightweight compatibility placeholder backed by version-like fields emitted from the current control snapshots.

## Claim Rules

- `full_service_semantic`: runtime preserved, state preserved, control semantics preserved or compatible changed, evidence preserved, high confidence
- `runtime_plus_state`: runtime preserved, state preserved or degraded, control semantics not incompatible, evidence not broken
- `runtime_only`: runtime preserved but stronger semantic claims are unsupported
- `unclaimable`: hard break or evidence continuity broken with insufficient state confidence

## Durable Checkpoints

The runtime epoch records:

- `last_successful_durable_checkpoint_at`
- `durable_checkpoint_interval_seconds`
- `durable_checkpoint_health`
- `evidence_write_failures_last_hour`
- `evidence_write_failures_last_24h`

These fields drive evidence continuity and claim downgrades.

## Next Hardening Steps

1. Add stable queue and inflight digests sourced from authoritative schedulers rather than directory snapshots.
2. Add explicit rollback detectors for registry, verification, and ledger regression.
3. Replace placeholder control semantic versions with real contract compatibility checks.
4. Distinguish `preserved but degraded` from `broken` in milestone narratives and dashboards.
