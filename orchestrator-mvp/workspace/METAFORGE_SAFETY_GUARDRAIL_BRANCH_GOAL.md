# MetaForge Safety Guardrail Branch Goal

Scope: only `D:\codex\orchestrator-mvp`

Do not modify:
- `D:\codex\generated\toy-os-demo`
- root control entry scripts under `D:\codex` unless a separately approved patch explicitly targets them
- approval and security boundaries through implicit runtime mutation

## Objective

Add a fourth architecture line: Safety Guardrail.

This line exists to prevent Self-Improvement, Research, or Evolution from:

- modifying critical control modules without approval
- corrupting persistent state
- promoting unsafe variants
- entering uncontrolled self-modification loops

## Core rule

Core Modules Immutable.

The following areas are immutable to automatic mutation unless routed through `approved_patch` or equivalent manual approval gate:

- control layer
- scheduler and orchestration control path
- state system and persistent state schema

Initial protected module families:

- `app/`
- `runtime/`
- `state/`
- control-critical parts of `tools/`

## Existing anchors

- `tools/ai_guard.py`
- `tools/privilege_policy.py`
- `tools/session_guard.py`
- `tools/change_request_analyzer.py`
- `tools/verification_engine.py`
- `tools/release_operations.py`

## Current gap

MetaForge already protects broad core paths and manual approval actions, but it does not yet expose a first-class immutable-core policy with explicit patch approval semantics for self-improving agents.

## Stage plan

### Stage 1: Immutable core registry

Deliverables:
- define exact immutable module families and protected file patterns
- distinguish mutable workspace files from immutable core modules

Required artifact:
- `data/core_immutability_policy.json`

Validation:
- static review against `ai_guard.py` protected paths and current approval policy

### Stage 2: Approved patch gate

Deliverables:
- define an explicit `approved_patch` record format for core changes
- require reviewer identity, reason, target files, validation plan, and rollback note

Required artifact:
- `data/approved_patch_policy.json`

Validation:
- static review that core-targeted actions cannot resolve as plain AUTO workspace writes

### Stage 3: Mutation blocker

Deliverables:
- add a mutation blocker decision that rejects autonomous writes to immutable core paths unless an approved patch record exists

Required artifact:
- `data/safety_guardrail_status.json`

Validation:
- verify autonomous mutation is blocked for immutable targets
- verify ordinary workspace writes remain unaffected

### Stage 4: Loop breaker

Deliverables:
- add a loop-risk signal for repeated self-modification attempts, repeated failed promotions, or repeated safety violations
- force downgrade to report-only mode when triggered

Required artifact:
- `data/self_modification_loop_guard.json`

Validation:
- static review against recent task and failure history
- confirm triggered state disables unsafe auto-promotion

## Acceptance rule

This branch goal counts only if MetaForge can explain why a core-targeting mutation was blocked, approved, or downgraded, with persisted policy artifacts.

## Downgrade rule

If mutation intent is ambiguous, default to report-only output and require explicit CEO review.
