# MetaForge OS High-Throughput Rollout

This is the first implementation slice for:

- `D:\codex\METAFORGE_OS_HIGH_THROUGHPUT_BLUEPRINT.md`

It keeps the rollout narrow and executable.

## Phase 1

Goal:

- industrialize evidence refresh before attempting broader product expansion

Tasks:

1. Enforce the task schema at dispatch time
2. Split work into `fastlane`, `build_test`, `regression`, and `incubation`
3. Require a verification level before execution
4. Enforce WIP caps per queue, project, and artifact
5. Publish the 8-metric throughput dashboard
6. Standardize report refresh, demo rebuild, harness run, and audit flows

## Phase 1 success criteria

- dispatches without schema fields are rejected
- short verification work is not blocked by long work
- each task has a chosen validation tier
- WIP conflicts are visible before execution
- the dashboard shows first-result, final-verdict, queue-wait, retry, and conversion metrics

## Phase 1 deliverables

- policy deltas in the control docs
- a queue admission rule
- a rollout checklist for the operator
- a metrics definition sheet

## Phase 1 boundary

- do not modify provider workspaces
- do not change runtime internals unless the control surface already routes through them
- do not expand into product code changes until the control-plane rules are in place

