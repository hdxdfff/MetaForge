# MetaForge OS Saturation Policy

This policy operationalizes `D:\codex\METAFORGE_OS_KPI_POLICY.md` and treats that file as the formal production specification.

## Goal

Keep the system productively saturated while maximizing verified delivery throughput.

This policy is operationalized by:

- `D:\codex\METAFORGE_OS_HIGH_THROUGHPUT_BLUEPRINT.md`

## Queue policy

- Maintain `3–6 × worker` executable tasks when capacity allows.
- For ToyOS, always keep `3–6` branch-scoped sub-tasks available.
- Prefer tasks that can yield a concrete artifact within `15–45 min`.
- Split large goals into parallel lanes with explicit deliverables.
- Bias the mix toward short verified work before long incubation work.
- Preserve evidence-refresh capacity for report, harness, and audit flows.

## Default queue mix

The default operating queues are:

- `fastlane`
- `build_test`
- `regression`
- `incubation`

Queue ownership should preserve verification flow:

- `fastlane` for low-risk atomic work
- `build_test` for build and smoke work
- `regression` for harness and evaluator work
- `incubation` for new product or architecture work

## Dispatch contract

Every dispatched task must include:
- scope boundary
- required artifact type
- validation requirement
- downgrade rule: if implementation is unsafe, emit patch proposal or branch goal
- task schema fields from the high-throughput blueprint
- a chosen verification level before execution

## Required output per cycle

Each worker cycle must produce at least one of:
- patch
- patch proposal
- branch goal
- test report
- risk list
- documentation delta

Outputs without a landing file or validation step count as non-productive.

## Idle detection

Mark a run as idle if any of the following is true:
- no artifact after `15–20 min`
- no file delta, report, or diagnosis after one work cycle
- output is generic discussion without actionable deliverable

## Recovery policy

- first idle run: re-scope task smaller
- second consecutive idle run on same route: lower route priority and switch worker
- repeated drift outside target workspace: convert route to proposal-only mode
- if the same artifact keeps getting reworked, split the work before retrying

## Anti-gaming rules

Treat the following as KPI failures:
- inflated code output without tests or validation
- repeated paraphrase of the same plan
- outputs that ignore scope boundaries
- artifacts written only to provider workspaces without returning usable output to the target workspace
- raw LOC growth used as success evidence

## ToyOS delivery rule

For ToyOS work, valid results must point back to `D:\codex\generated\toy-os-demo`.
If a worker writes only into provider or factory workspaces, the run does not count as ToyOS delivery.

## Scheduling hints

Priority queue order:
- critical
- kernel
- core
- feature
- tests
- docs

## WIP limits

Use these controls as the default operating envelope:

- per queue
- per project
- per artifact

Scheduling formula:
`score = priority × success_rate × speed`

## Minimum productivity target

Per active hour, each lane should produce:
- `1–3` verifiable delivery units, or
- one bounded failure report with next action
