# MetaForge 6-Hour Recursive Execution Handoff

Updated: 2026-03-12
Owner after handoff: MetaForge control layer, self-improvement loop, and worker lanes
Execution window: complete within 6 hours from acceptance of this brief

## Objective

Use the next 6 hours to convert MetaForge from a partially recursive factory into a controlled closed loop that can:

1. detect failures from runtime evidence
2. prioritize bounded self-improvement work
3. validate changes automatically
4. produce merge-ready or blocked-with-evidence outcomes
5. avoid unsafe controller-core mutation

## Current baseline

As of 2026-03-12:

- `daemon-status` is readable again after repairing `tools/factory_daemon.py`
- control layer status is `constrained`
- engineering OS status is `attention`
- patch gate status is `attention`
- autonomy score is `0.685` with `stage4_confirmed`
- quality score is `0.9162`
- release train status is `blocked`
- tool health still reports `daemon-not-running`
- recent daemon log still contains `OSError: [Errno 22] Invalid argument`

## Hard execution rules

- Primary lane only: self-improvement and verification
- Do not expand research, web-product, or ToyOS work
- Do not mutate `app/`, `runtime/`, `state/`, scheduler core, or approval policy without explicit approved-patch handling
- Do not count prose as progress; count only updated artifacts, validation outputs, or merge handoff records
- If daemon errors recur for 2 consecutive cycles, stop patch generation and switch to blocker-report mode

## 6-hour phase plan

### Phase 0: first 30 minutes

Goal: stabilize the execution surface.

Required actions:

- refresh `daemon-status`
- refresh `control-layer-status`
- refresh `engineering-os-status`
- refresh `lab-status`
- refresh `autonomy-score`
- confirm no new syntax or import failures in controller-facing tools
- inspect latest daemon log tail and isolate any new `Invalid argument` source before broader self-improvement work

Required output:

- updated status evidence in runtime data files
- one brief blocker note if daemon instability persists

Gate to continue:

- status commands succeed
- no new import-time crash in control modules

### Phase 1: hour 0.5 to 2

Goal: normalize and rank recursive work from existing evidence.

Use these artifacts as the source of truth:

- `data/self_improvement_backlog.json`
- `data/self_improvement_plan.json`
- `data/self_improvement_status.json`
- `data/self_improvement_handoff.json`
- `data/verification_status.json`
- `data/tool_health_history.json`
- `data/telemetry_events.json`

Priority order:

1. daemon and runtime health blockers
2. verification blockers that are workspace-safe
3. telemetry and throughput remediation
4. release handoff artifacts
5. manual-gate controller work as proposal only

Expected decisions:

- keep `control-layer-lags-quality` as proposal-only unless operator approval exists
- keep any core-path mutation behind `approved_patch`
- prioritize bounded candidates such as runtime health, telemetry, and handoff improvements

Required output:

- refreshed candidate ordering with explicit `auto` vs `manual` lane separation

### Phase 2: hour 2 to 4

Goal: execute only bounded auto-safe improvements.

Allowed mutation areas:

- telemetry enrichment
- self-improvement artifact generation
- task/runtime hygiene in workspace-safe tool modules
- verification artifact quality
- release handoff templates

Disallowed without manual approval:

- decision engine promotion logic
- privilege policy changes
- core controller routing semantics
- broad scheduler changes

For each executed candidate, require:

- target files
- validation command
- residual risk
- rollback note

Required output:

- refreshed `self_improvement_status.json`
- refreshed `self_improvement_handoff.json`
- any generated patch evidence bundles

### Phase 3: hour 4 to 5.5

Goal: verify loop quality, not just patch count.

Required checks:

- verification compile path still passes
- tool health issues do not increase
- daemon log does not gain a fresh repeated runtime error signature
- release operations status is refreshed
- patch submissions are either merge-ready with evidence or explicitly blocked

Success threshold for this phase:

- at least one bounded candidate reaches validated or merge-ready state
- no uncontrolled core mutation occurs
- status evidence remains machine-readable

### Phase 4: final 30 minutes

Goal: produce the operator-facing closing evidence.

Required output under `D:\codex\generated\metaforge-ai-factory`:

- `recursive-6h-execution-plan.md`
- at least one updated machine-readable runtime artifact from the self-improvement loop
- a short closing summary with changed files, validation, and residual risk

## Success condition

The 6-hour run counts as successful only if MetaForge can show all of the following:

- it consumed real failure evidence
- it prioritized bounded work instead of spawning uncontrolled goals
- it validated at least one change automatically
- it emitted merge-ready or blocked-with-evidence output
- it preserved control-plane safety boundaries

## Failure fallback

If the daemon becomes unstable again, or the next improvement requires core controller mutation, stop autonomous execution and emit a blocker package with:

- failing evidence
- suspected module
- why auto-execution stopped
- what manual approval is required

## Operator note

Treat this file as the active 6-hour recursive execution brief. Prefer existing controller and self-improvement artifacts over new ad hoc planning files.
