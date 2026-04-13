# MetaForge OS Workspace Lock Enforcement Proposal

Scope: proposal only

This document refines the existing routing-guard proposal into one narrower implementation target:

`workspace_locked` must become a real control-layer constraint instead of prompt-only metadata.

## Problem

The system already carries lane, target-workspace, and `workspace_locked` intent in prompts and docs, but the runtime still rewrites execution into provider workspaces.

Observed current contradiction:

- requested target workspace: `D:\codex\generated\toy-os-demo`
- actual active execution root: `D:\codex\orchestrator-mvp\workspace\strengthen-agent-orchestration-capability`

Under current KPI rules, this makes the run an invalid delivery.

## Why the current behavior is wrong

The current runtime treats capability routing as if it is also workspace selection.
That mixes two different concerns:

- capability hinting
- execution-root authority

For bounded branch work, capability routing may add metadata, but it must not overrule the requested execution root.

## Proposed policy

If a dispatch is marked `workspace_locked=true`, then:

1. the original target workspace remains the task `repo_path`
2. provider routing may still attach:
   - worker hints
   - capability class
   - VM hints
   - verification hints
3. provider routing may not replace:
   - `repo_path`
   - artifact return path
   - authoritative validation root

## Minimal patch shape

### Patch 1: dispatch payload model

Add or formalize these fields in dispatch payloads:

- `target_workspace`
- `workspace_locked`
- `lane_type`
- `return_path`

### Patch 2: orchestrator routing guard

Before `_apply_capability_route` mutates the task:

- compare resolved project workspace and target workspace
- if `workspace_locked=true`, keep `repo_path=target_workspace`
- record selected provider only as metadata

### Patch 3: invalid-delivery classification

If runtime execution root differs from locked target workspace:

- mark the run as `route_drift`
- mark resulting output as `invalid_delivery`
- exclude it from VDU accounting

### Patch 4: workboard visibility

Expose these fields in status/workboard outputs:

- `target_workspace`
- `execution_root`
- `workspace_locked`
- `route_drift`
- `invalid_delivery`

## Suggested pseudocode

```text
if task.workspace_locked:
    task.repo_path = task.target_workspace
    task.provider_workspace = selected_provider.workspace
    task.execution_root = task.target_workspace
else:
    task.repo_path = selected_provider.workspace or task.repo_path
```

Then later:

```text
if task.workspace_locked and task.execution_root != task.target_workspace:
    task.route_drift = true
    task.invalid_delivery = true
```

## Acceptance criteria

This proposal is only accepted if all of the following are true:

1. A `workspace_locked=true` ToyOS dispatch keeps execution rooted at `D:\codex\generated\toy-os-demo`.
2. Provider selection still appears in metadata for analysis/debugging.
3. Outputs landing only in provider workspaces are marked invalid.
4. Status/workboard output makes drift visible without log-diving.
5. Non-locked web/platform tasks still keep their old provider-routing behavior.

## Regression tests

1. Locked ToyOS report task

- target workspace: `D:\codex\generated\toy-os-demo`
- expected execution root: same as target

2. Locked ToyOS branch-goal task

- target workspace: `D:\codex\generated\toy-os-demo`
- expected artifact lands there

3. Unlocked platform task

- expected provider workspace routing still works

## Relationship to current lane system

This proposal is the missing runtime counterpart to the lane layer already implemented in the workspace:

- lane assets
- lane registry
- lane workboard
- open-lane command

Those pieces already define authority.
This proposal makes the runtime obey that authority.

## Immediate branch goal

`Make workspace_locked authoritative for execution-root selection while preserving provider metadata and non-locked routing behavior.`
