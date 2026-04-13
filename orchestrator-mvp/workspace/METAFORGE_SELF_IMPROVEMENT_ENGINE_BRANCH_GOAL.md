# MetaForge Self-Improvement Engine Branch Goal

Scope: only `D:\codex\orchestrator-mvp`

Do not modify:
- `D:\codex\generated\toy-os-demo`
- `D:\codex\opencode-control.ps1`
- `D:\codex\factoryctl.cmd`
- external provider workspaces unless a bounded patch explicitly targets them

## Objective

This is the only active primary line.

Upgrade the current self-patch loop into a real closed-loop self-improvement engine that can:

1. detect bug or quality failure
2. generate bounded patch
3. run tests automatically
4. produce merge-ready result
5. merge only through the approved gate

## Stage-4 metric

Self-Improvement succeeds only when MetaForge can automatically complete:

- find bug
- generate patch
- pass tests
- merge code

Until then, MetaForge is not Stage-4.

## Existing anchors

- `tools/self_patch_loop.py`
- `tools/prepare_self_patch_branch.py`
- `tools/verification_engine.py`
- `tools/release_operations.py`
- `tools/tool_health_audit.py`
- `tools/change_request_analyzer.py`
- `tools/environment_repair_lane.py`

## Current gap

The current loop can convert findings into candidates and prepare a logical branch record, but it does not yet maintain a full delivery loop for:

- bug intake tied to real failures
- patch candidate generation tied to target files
- automatic test execution tied to each candidate
- merge readiness and approved-merge handoff

## Stage plan

### Stage 1: Bug-to-candidate normalization

Deliverables:
- normalize runtime failures, tool health issues, and verification failures into a single self-improvement backlog
- each item must include target files, severity, and validation method

Required artifact:
- `data/self_improvement_backlog.json`

Validation:
- static schema review
- cross-check candidate counts against `self_patch_candidates.json`

### Stage 2: Patch candidate generation

Deliverables:
- generate bounded patch candidates from backlog items
- separate proposal-only items from sandbox-runnable items

Required artifact:
- `data/self_improvement_plan.json`

Validation:
- static review against `prepare_self_patch_branch.py`
- confirm every planned item has target files and a validation method

### Stage 3: Automatic testing

Deliverables:
- connect patch candidates to automated validation
- persist pass/fail results and residual risk

Required artifact:
- `data/self_improvement_status.json`

Validation:
- verify failing candidates remain blocked
- verify passing candidates include exact tests or validation steps run

### Stage 4: Merge handoff

Deliverables:
- create merge-ready records for validated patch candidates
- include branch, tests run, residual risk, rollback note, and approval requirement

Required artifact:
- `data/self_improvement_handoff.json`

Validation:
- verify only passing candidates can enter merge-ready state
- verify immutable-core targets require approved-patch handling

## Acceptance rule

A stage only counts if it lands as a concrete data artifact or tool update under `orchestrator-mvp` and includes explicit validation notes.

## Downgrade rule

If safe implementation is ambiguous, emit a patch proposal or blocker report instead of pretending patch-test-merge is complete.
