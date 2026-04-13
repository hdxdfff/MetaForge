# MetaForge OS ToyOS Routing Guard Patch Proposal

## Scope

This document proposes a bounded platform-side fix for ToyOS dispatch routing.
It does not apply the control-layer change directly.

## Problem

ToyOS-targeted dispatches that explicitly require output under `D:\codex\generated\toy-os-demo` are being routed into provider workspaces such as `D:\codex\orchestrator-mvp\workspace\build-ai-video-factory`.

This violates the active KPI policy because provider-only output does not count as ToyOS delivery.

## Reproduced failure

Observed dispatch task ids:

- `4fc4b875d17a484baaf709b1734879e9`
- `8539b2b7c00b44c6a41a58c87c72515f`

Observed result:

- tasks were accepted
- capability route selected `webapp_generation`
- provider workspace became `D:\codex\orchestrator-mvp\workspace\build-ai-video-factory`
- no `TOYOS_PAGING_STAGE0_BRANCH_GOAL.md` returned to `D:\codex\generated\toy-os-demo`
- no `TOYOS_REGRESSION_TEST_PLAN.md` returned to `D:\codex\generated\toy-os-demo`

By current KPI rules, this is an invalid VDU.

## Root cause

### 1. Capability routing ignores the already-resolved ToyOS project workspace

In `dispatch_task`, the request first resolves the project repo path, but `_select_capability_route` does not use that project identity to constrain routing.

Relevant code:

- `D:\codex\orchestrator-mvp\app\orchestrator.py:123`
- `D:\codex\orchestrator-mvp\app\orchestrator.py:126`
- `D:\codex\orchestrator-mvp\app\orchestrator.py:272`
- `D:\codex\orchestrator-mvp\app\orchestrator.py:286`

Current behavior:

- `repo_path` is correctly resolved from the ToyOS project
- capability selection still uses only prompt text
- no hard preference is applied for the current project workspace

### 2. Capability routing is keyword-score based and globally biased toward `webapp_generation`

Relevant code:

- `D:\codex\orchestrator-mvp\tools\capability_registry.py:72`
- `D:\codex\orchestrator-mvp\tools\capability_registry.py:86`
- `D:\codex\orchestrator-mvp\tools\capability_registry.py:90`
- `D:\codex\orchestrator-mvp\data\global_policy_state.json:3`

Current behavior:

- route score is a keyword count plus hint/reputation/focus bonuses
- `webapp_generation` is globally favored
- generic tokens such as `app` and `backend` are enough to give many providers a non-zero score

### 3. Selected provider workspace overwrites the original ToyOS repo path

Relevant code:

- `D:\codex\orchestrator-mvp\app\orchestrator.py:127`
- `D:\codex\orchestrator-mvp\app\orchestrator.py:288`
- `D:\codex\orchestrator-mvp\app\orchestrator.py:298`
- `D:\codex\orchestrator-mvp\app\orchestrator.py:315`

Current behavior:

- once a capability is selected, `_apply_capability_route` replaces `repo_path` with the provider workspace
- the rest of the task is then contextualized and executed against the wrong workspace

### 4. Capability registry currently exposes ToyOS-related providers as `webapp_generation`

Relevant data:

- `D:\codex\orchestrator-mvp\factory\capability_registry.json`

Observed issue:

- `Continue ToyOS kernel branch work with mainline context reuse` is registered under `webapp_generation`
- its keywords are `web`, `frontend`, `backend`, `site`, `app`
- this increases false matches for non-web tasks

## Proposed patch

### Patch A: add target-workspace lock before applying provider workspace

Target file:

- `D:\codex\orchestrator-mvp\app\orchestrator.py`

Proposal:

- introduce a routing guard that compares the resolved `repo_path` and `project.repo_path`
- if the target workspace is a registered project like ToyOS, do not let capability routing overwrite `repo_path`
- allow provider hints to remain as advisory context only

Suggested rule:

- if `repo_path` is set and the request explicitly says `Operate only on <repo_path>` or names a registered project workspace, keep execution rooted at that workspace
- attach provider context as metadata, not as execution workspace override

### Patch B: add explicit `workspace_locked` or `enforce_repo_path` dispatch flag

Target file:

- `D:\codex\orchestrator-mvp\app\models.py`
- `D:\codex\orchestrator-mvp\app\orchestrator.py`
- any request builder that creates dispatch payloads

Proposal:

- add a boolean dispatch flag for bounded branch work
- when enabled, `_apply_capability_route` cannot replace the original repo path
- this should be the default for branch-scoped ToyOS work

### Patch C: add project-aware routing short circuit for ToyOS

Target file:

- `D:\codex\orchestrator-mvp\app\orchestrator.py`
- optionally `D:\codex\orchestrator-mvp\tools\capability_registry.py`

Proposal:

- if the project or repo path maps to `D:\codex\generated\toy-os-demo`, prefer no provider reroute
- only use capability routing to select worker hints, VM template hints, or verification hints
- do not use it to change workspace

### Patch D: split capability scoring from workspace selection

Target file:

- `D:\codex\orchestrator-mvp\tools\capability_registry.py`
- `D:\codex\orchestrator-mvp\app\orchestrator.py`

Proposal:

- capability route may choose a capability class
- workspace selection must be resolved independently from project identity and task scope
- provider workspace reuse should require explicit opt-in

### Patch E: correct misleading ToyOS-related capability registration

Target file:

- `D:\codex\orchestrator-mvp\factory\capability_registry.json`
- platform generation path that emits those capabilities

Proposal:

- stop registering ToyOS-support platforms as `webapp_generation`
- add a dedicated capability such as `kernel_os_dev` or `teaching_kernel_dev`
- use keywords like `kernel`, `os`, `paging`, `syscall`, `scheduler`, `qemu`, `elf`, `ring3`, `filesystem`

This is not required for the immediate containment fix, but it is required for long-term routing correctness.

## Minimal safe implementation order

1. Apply Patch A.
2. Apply Patch B.
3. Re-run the two failed ToyOS dispatches.
4. If routing still drifts, apply Patch C.
5. After stability is proven, apply Patch E.

## Acceptance criteria

A fix is accepted only if all of the following are true:

- a ToyOS dispatch with explicit target `D:\codex\generated\toy-os-demo` keeps `task.repo_path` rooted there
- provider workspace may appear in metadata, but not as the task execution root
- output files land in `D:\codex\generated\toy-os-demo`
- provider-only output is rejected and marked as invalid delivery
- at least two repeated ToyOS dispatches return bounded artifacts to the target workspace

## Regression tests

### Test 1: ToyOS branch goal dispatch

Dispatch:

- target `D:\codex\generated\toy-os-demo`
- artifact `TOYOS_PAGING_STAGE0_BRANCH_GOAL.md`

Expected:

- `repo_path` remains `D:\codex\generated\toy-os-demo`
- artifact appears in target workspace

### Test 2: ToyOS test plan dispatch

Dispatch:

- target `D:\codex\generated\toy-os-demo`
- artifact `TOYOS_REGRESSION_TEST_PLAN.md`

Expected:

- `repo_path` remains `D:\codex\generated\toy-os-demo`
- artifact appears in target workspace

### Test 3: normal capability-routed web task

Dispatch a true frontend task.

Expected:

- provider routing still works for actual web work
- no regression in existing `webapp_generation` flows

## KPI interpretation

Under the active KPI policy:

- current observed runs count as failed delivery
- the failure class is `route drift outside target workspace`
- fixing this should be prioritized over increasing worker throughput

## Branch goal

Branch goal for platform side:

`Enforce target-workspace routing integrity for bounded ToyOS dispatches while preserving provider metadata and non-ToyOS capability routing.`
