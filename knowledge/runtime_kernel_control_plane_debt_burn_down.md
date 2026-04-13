# Runtime Debt Burn-Down

Purpose: reduce structural debt without destabilizing the live system.

## Target split

- Runtime kernel
  - Owns heartbeat, watchdog, task dispatch, durable checkpoints, and source-of-truth runtime status.
- Control plane
  - Owns routing, verification, quality scoring, identity refresh, memory hygiene, and release gates.
- Delivery plane
  - Owns target workspace execution, artifact generation, artifact verification, and promotion evidence.

## Phase 1

- Stop stale memory and stale status from being treated as healthy.
- Make time-sensitive scorecards refresh when validity windows expire.
- Remove ambiguous status readers so Windows-local stale files cannot override VM truth.

## Phase 2

- Slim the daemon hot path to runtime-kernel concerns.
- Move verification, control-layer refresh, identity refresh, and self-model work onto asynchronous or sampled control-plane paths.
- Keep publish cadence explicit and observable.

## Phase 3

- Freeze contracts between runtime, control, and delivery.
- Define task state transitions, artifact evidence schema, release-gate inputs, and handoff lifecycle rules.
- Make VM state the single live runtime truth source.

## Phase 4

- Migrate only the runtime kernel to Rust if Python still remains the bottleneck after the split.
- Keep control-plane logic language-agnostic and contract-driven.

## Done means

- No active handoff can remain expired without surfacing in live scorecards.
- No operator command can silently read stale local runtime state when VM state is authoritative.
- The daemon can keep ticking even when control-plane jobs fail or pause.
- Delivery metrics count only verified real artifacts.
