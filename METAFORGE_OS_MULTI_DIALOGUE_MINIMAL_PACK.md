# MetaForge OS Multi-Dialogue Minimal Implementation Pack

## Purpose

This pack reduces the full multi-dialogue architecture into the smallest safe implementation that can be adopted first.

It is intentionally minimal.
It does not require unrestricted control-layer redesign before first use.

## Included units

### 1. Lane registry

Add a lane registry file:

- `dialogue_lanes.json`

Minimum fields per lane:

- `dialogue_id`
- `lane_type`
- `target_workspace`
- `allowed_scope`
- `forbidden_scope`
- `priority`
- `merge_policy`
- `workspace_locked`

### 2. Lane-aware dispatch fields

Every dispatch payload should accept:

- `dialogue_id`
- `lane_type`
- `target_workspace`
- `workspace_locked`

Minimal rule:

- if `workspace_locked=true`, provider routing may attach metadata but may not replace execution root

### 3. CEO arbitration pass

Before mutating work starts, run one lightweight pass:

- load all active lanes
- detect workspace overlap
- classify lanes as `execute`, `queue`, or `proposal-only`

### 4. Promotion gate

Outputs remain lane-local until one of the following holds:

- non-overlapping artifact
- verified bounded patch
- approved proposal or branch goal

## Minimal rollout order

1. Add lane registry file support.
2. Add `workspace_locked` to dispatch payloads.
3. Make CEO arbitration read active lanes before mutating execution.
4. Block execution root replacement when lane is locked.
5. Add promotion gate for overlapping lanes.

## Minimal first lanes

### Lane A

- `dialogue_id`: `main-dialogue`
- `lane_type`: `product`
- `target_workspace`: `D:\codex\generated\toy-os-demo`
- `merge_policy`: `bounded-branch`

### Lane B

- `dialogue_id`: `routing-repair-dialogue`
- `lane_type`: `platform`
- `target_workspace`: `D:\codex`
- `merge_policy`: `proposal-only`

### Lane C

- `dialogue_id`: `verification-dialogue`
- `lane_type`: `verification`
- `target_workspace`: `D:\codex\generated\toy-os-demo`
- `merge_policy`: `report-only`

## Minimal success condition

The first implementation is successful if:

- two or more dialogues can be active at once
- a locked ToyOS lane keeps its execution root
- a platform lane can run in proposal-only mode without blocking product work
- verification lane can observe and report without corrupting product scope

## Immediate KPI tie-in

This minimal pack should improve:

- scope integrity
- route drift detection
- invalid delivery rejection
- safe parallel throughput

It should not be judged by raw throughput alone.
