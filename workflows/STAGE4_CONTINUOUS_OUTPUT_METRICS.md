# Stage 4 Continuous Output Metrics

## Purpose

After the first confirmed `stage4_confirmed` baseline, the next question is not "am I confirmed?" but "can I keep producing verified output?"

This workflow tracks sustained output over 24h and 72h windows.

## Live Metrics File

The live report is written to:

- [`D:\codex\orchestrator-mvp\data\continuity_metrics.json`](D:\codex\orchestrator-mvp\data\continuity_metrics.json)

The generator is:

- [`D:\codex\orchestrator-mvp\tools\continuity_metrics.py`](D:\codex\orchestrator-mvp\tools\continuity_metrics.py)

## Metric Family

Track these groups together:

1. Real artifact throughput
2. Verified task throughput
3. Median task cycle time
4. Release output
5. Self-recovery
6. Backlog replenishment
7. Blocked-to-done conversion

## 24h / 72h Targets

Use the following starting thresholds:

- Real artifacts: at least `1` in 24h and `3` in 72h
- Verified completed tasks: at least `5` in 24h and `15` in 72h
- Median task cycle time: at most `60` minutes in 24h and `90` minutes in 72h
- Self-recovery rate: at least `0.75` in 24h and `0.80` in 72h
- Backlog replenishment: nonzero ready nodes and stable active goal feed

## Current Rule

Do not use autonomy score as the output target. Treat `stage4_confirmed` as the starting condition, then optimize for sustained delivery quality.

## Hard Requirement

Blocked-to-done conversion must come from a real transition ledger. Snapshot-only history is not enough.

## Refresh Procedure

1. Run the continuity metrics generator.
2. Inspect the 24h and 72h windows together.
3. Compare against the previous snapshot.
4. If a metric regresses, record the cause and do not overwrite the previous baseline.

## Recommended Automation

Install the hourly refresh task with:

- [`D:\codex\orchestrator-mvp\install-continuity-metrics-task.ps1`](D:\codex\orchestrator-mvp\install-continuity-metrics-task.ps1)

The task runs:

- [`D:\codex\orchestrator-mvp\run-continuity-metrics.ps1`](D:\codex\orchestrator-mvp\run-continuity-metrics.ps1)

Suggested cadence:

- every `60` minutes

## Current Baseline

The first confirmed baseline package is:

- [`D:\codex\generated\stage4-confirmed-baseline-20260403`](D:\codex\generated\stage4-confirmed-baseline-20260403)

The live sustained-output context is:

- `control_layer_status = stable`
- `autonomy_stage = stage4_confirmed`
- `artifact_registry = pass`
- `reality_dashboard = pass`
- `release_operations = pass`
