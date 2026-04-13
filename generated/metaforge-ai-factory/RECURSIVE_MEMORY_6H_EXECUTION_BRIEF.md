# Recursive Memory 6H Execution Brief

Updated: 2026-03-12
Owner after handoff: MetaForge control layer and worker system
Target window: complete within 6 hours of dispatch
Primary delivery directory: `D:\codex\generated\metaforge-ai-factory`

## Mission

Stand up a minimal recursive memory implementation path that improves future execution quality without broad controller mutation.

## Constraints

- Do not mutate core controller policy or privilege rules in this run.
- Prefer reports, low-risk tooling, and generated evidence over architectural churn.
- Keep all operator-facing outputs under `D:\codex\generated\metaforge-ai-factory`.
- If runtime health degrades further, pause feature work and emit blocker evidence.

## Starting State

- `engineering-os-status`: pass
- `control-layer-status`: constrained
- `daemon-status`: readable again after syntax repair, but daemon still reports `OSError: [Errno 22] Invalid argument` in recent ticks
- `ai_testing`: pass
- Highest immediate runtime risk: daemon health noise and active task throttle pressure

## Delivery Scope

### Phase 0: Stabilize execution surface (0h to 1h)

Required outputs:

- `recursive_memory_runtime_blockers.md`
- short diagnosis of daemon `Invalid argument` source or containment path
- confirmation that status commands remain readable after any change

Definition of done:

- blocker cause is identified or tightly bounded
- no new controller-core mutations beyond bounded bug fix

### Phase 1: Instrument memory pipeline (1h to 2.5h)

Required outputs:

- `recursive_memory_event_schema.json`
- `recursive_memory_episode_schema.json`
- `recursive_memory_pipeline_map.md`

Implementation target:

- define `event`, `episode`, `reflection`, `pattern_candidate` structures
- map current runtime artifacts to those structures
- identify reuse points in existing knowledge and task state stores

Definition of done:

- schemas are machine-readable
- every field has an identified source or explicit `missing` note

### Phase 2: Add reflection and consolidation design (2.5h to 4h)

Required outputs:

- `recursive_memory_reflection_contract.json`
- `recursive_memory_consolidation_rules.md`
- `recursive_memory_injection_points.md`

Implementation target:

- reflection outputs must include `failure_cause`, `decision_error`, `tool_gap`, `workflow_gap`, `reusable_fix`, `confidence`, `scope`
- consolidation thresholds must gate promotion from event to pattern to knowledge
- injection points must specify how approved memory changes planning or routing

Definition of done:

- reflection schema is structured, not prose-only
- consolidation rules include promotion thresholds
- at least 3 concrete injection points are named in the current system

### Phase 3: Produce MVP implementation path (4h to 5.5h)

Required outputs:

- `recursive_memory_mvp_backlog.json`
- `recursive_memory_patch_targets.md`
- `recursive_memory_validation_plan.md`

Implementation target:

- propose bounded file targets
- split work into low-risk tasks for instrumentation, reflection store, and planning injection
- attach cheapest-first validation for each work item

Definition of done:

- backlog is dispatchable as separate low-risk tasks
- each item has output path and validation path

### Phase 4: Final evidence package (5.5h to 6h)

Required outputs:

- `recursive_memory_readout.md`
- `recursive_memory_risks.md`

Definition of done:

- readout states what was changed, what was only designed, and what remains blocked
- residual risk is explicit

## Required Success Conditions

- At least 8 new artifacts exist under `D:\codex\generated\metaforge-ai-factory`
- One machine-readable backlog exists and can be dispatched in bounded chunks
- The plan includes a direct path from `experience -> reflection -> consolidation -> strategy injection`
- Status command regressions are not reintroduced

## Guardrails

- No claim of self-evolving behavior without evidence of strategy injection points
- No broad mutation of `app`, `runtime`, or privilege policy during this 6-hour run unless explicitly escalated
- Prefer bounded fixes in `tools` plus generated artifacts

## Dispatch Recommendation

Use the current work as a research-lane plus chore-lane hybrid:

- research-lane: design schemas, reflection contract, consolidation rules, injection points
- chore-lane: generated reports, backlog packaging, evidence refresh
- runtime stabilization: only bounded fix for daemon `Invalid argument` if diagnosis stays inside a small surface
