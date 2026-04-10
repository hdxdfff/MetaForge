# MetaForge OS Multi-Dialogue Parallel Development Proposal

## Scope

This is a platform-side architecture proposal for allowing multiple dialogues to develop and upgrade the system in parallel.
It does not directly modify the main control layer.

## Goal

Allow multiple active dialogues to work at the same time without collapsing into shared-state corruption, route drift, or duplicate work.

The target outcome is:

- many dialogues can run concurrently
- each dialogue has bounded ownership
- all dialogues share a common self/state/world model
- merge or promotion still happens through a controlled gate

## Problem

Right now the system can execute multiple tasks, but dialogue-level concurrency is not treated as a first-class operating structure.

This causes several risks:

- multiple dialogues may mutate the same workspace without explicit lane ownership
- one dialogue may not see another dialogue's state clearly
- system upgrades and product work can collide
- routing may optimize for provider reuse rather than dialogue scope integrity
- the system behaves like parallel workers, not like a coordinated multi-threaded organization

## Required architecture

### 1. Dialogue as a first-class branch lane

Each dialogue must map to a bounded execution lane.

Minimum lane fields:

- `dialogue_id`
- `lane_type`
- `target_workspace`
- `allowed_scope`
- `forbidden_scope`
- `current_goal`
- `priority`
- `merge_policy`

Example lane types:

- product lane
- platform lane
- verification lane
- research lane
- self-upgrade lane

## 2. Shared self/state/world kernel

All dialogues must read the same:

- self model
- state model
- world model

This ensures every dialogue answers the same questions:

- who is the system
- what is the current state
- what world is being acted on

Dialogue lanes do not get separate identities.
They get separate scopes under one identity.

## 3. Dialogue-local memory plus global memory

Each dialogue should have:

- local branch memory
- local decisions
- local artifacts

The system should also preserve:

- global identity
- global state snapshot
- global project ledger
- global escalation inbox

Rule:

- identity is shared
- state is shared but lane-tagged
- execution artifacts are lane-local until promoted

## 4. CEO-agent arbitration

A resident CEO agent must coordinate all active dialogues.

Its responsibilities in multi-dialogue mode:

- assign lane ownership
- detect scope collisions
- prioritize conflicting work
- prevent two dialogues from silently editing the same target area
- decide whether a lane should execute, pause, degrade, or wait

## 5. Merge gate between dialogues

Parallel dialogue work must converge through a merge gate.

Possible merge outcomes:

- auto-merge for non-overlapping low-risk artifacts
- review-required for shared workspace overlap
- proposal-only if route or validation integrity is weak
- reject if lane violates target workspace or scope boundaries

## Proposed data model

### dialogue_lanes.json

Suggested state file:

`D:\codex\orchestrator-mvp\data\dialogue_lanes.json`

Example schema:

```json
[
  {
    "dialogue_id": "main-dialogue",
    "lane_type": "product",
    "target_workspace": "D:\\codex\\generated\\toy-os-demo",
    "allowed_scope": [
      "D:\\codex\\generated\\toy-os-demo"
    ],
    "forbidden_scope": [
      "D:\\codex\\orchestrator-mvp\\app",
      "D:\\codex\\orchestrator-mvp\\tools"
    ],
    "current_goal": "advance ToyOS mainline delivery",
    "priority": "high",
    "merge_policy": "bounded-branch"
  }
]
```

### dialogue_events.json

Suggested event file:

`D:\codex\orchestrator-mvp\data\dialogue_events.json`

Purpose:

- lane creation
- lane pause
- lane promotion
- lane conflict
- lane merge decision

## Scheduling rules

### Rule 1: no unscoped dialogue execution

A dialogue may not execute mutating work unless it has:

- a target workspace
- an allowed scope
- a forbidden scope
- a delivery type

### Rule 2: shared workspace requires arbitration

If two dialogues target the same workspace:

- the CEO layer must check for file overlap
- if overlap exists, one lane becomes active and the other becomes proposal-only or queued

### Rule 3: self-upgrade dialogue cannot silently override product dialogue

Self-upgrade work must not silently break product lanes.

If a platform lane touches routing, permissions, or state logic while a product lane is active:

- require patch proposal mode
- or require merge gate review

### Rule 4: route integrity beats throughput

If concurrent dialogues increase route drift or invalid delivery:

- reduce concurrency
- do not reward the extra throughput

## Upgrade model

Parallel upgrade means two classes of work can happen at once:

- product delivery
- system upgrade

But they must be separated by lane type.

Example:

- dialogue A: ToyOS product lane
- dialogue B: MetaForge routing-repair lane
- dialogue C: KPI/reporting lane

All three may run in parallel if:

- lane scope is explicit
- merge policy is explicit
- CEO arbitration is active

## Minimum implementation plan

### Patch A: add dialogue lane registry

Target area:

- control-layer state store

Add:

- `dialogue_lanes.json`
- lane lifecycle operations

### Patch B: add lane-aware dispatch

Dispatch payload should include:

- `dialogue_id`
- `lane_type`
- `target_workspace`
- `workspace_locked`

### Patch C: add collision detection

Before mutating work starts:

- compare active lane scopes
- detect file or workspace overlap
- downgrade or queue conflicting lanes

### Patch D: add CEO multi-dialogue arbitration

CEO agent should:

- inspect all active lanes
- emit lane priorities
- classify conflicts
- choose which lanes can execute now

### Patch E: add promotion gate

Lane outputs should be:

- lane-local first
- promoted to shared/main state only after verification and scope checks

## Acceptance criteria

The feature is accepted only if all of the following are true:

- at least two dialogues can run in parallel with distinct lane ids
- each dialogue has explicit scope and merge policy
- shared self/state/world remains consistent
- conflicting lanes are detected before mutating overlap
- product and self-upgrade lanes can coexist without silent overwrite
- invalid provider-only output still fails KPI accounting

## Recommended first use

Initial parallel layout:

- main dialogue: ToyOS delivery lane
- second dialogue: MetaForge routing-repair proposal lane
- third dialogue: verification and KPI observation lane

This gives safe concurrency without requiring immediate unrestricted control-layer edits.

## Branch goal

`Turn dialogue threads into lane-scoped parallel execution units coordinated by a shared CEO/state kernel and a merge gate.`
