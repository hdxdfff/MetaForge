# MetaForge OS Memory Schema v1

This workspace now treats memory as typed objects instead of only kernel snapshots.

## Stores

- Verified objects: `D:\codex\orchestrator-mvp\data\memory_objects.jsonl`
- Candidate objects: `D:\codex\orchestrator-mvp\data\memory_candidates.jsonl`
- Shared dialogue ledger: `D:\codex\orchestrator-mvp\data\dialogue_memory.json`
- Session index: `D:\codex\knowledge\dialogue-memory\session_index.json`

## Supported object types

- `fact`
- `procedure`
- `decision`
- `failure_fix`
- `handoff`

## Control commands

```powershell
D:\codex\factoryctl.cmd memory-object-status
D:\codex\factoryctl.cmd memory-bootstrap
D:\codex\factoryctl.cmd memory-recall validation --workspace D:\codex --type decision
D:\codex\factoryctl.cmd memory-promote --candidate-id <id>
```

## Current injection points

- `tools/memory_system.py` includes object-store summaries in `memory_kernel.json`.
- `tools/context_builder.py` injects a compact memory recall into context packages.
- `tools/codex_control.py` exposes the memory store through control commands.

## Minimal operating rule

- Store typed memory objects in the verified JSONL store.
- Park uncertain items in the candidate store.
- Promote only when the object is backed by evidence and useful reuse value.
- Keep handoff objects short and current.

## Fixed benchmark

The benchmark contract is defined in [`D:\codex\knowledge\memory_muscle_benchmark_v1.json`](D:/codex/knowledge/memory_muscle_benchmark_v1.json).
The evaluator lives in [`D:\codex\orchestrator-mvp\tools\memory_muscle_benchmark.py`](D:/codex/orchestrator-mvp/tools/memory_muscle_benchmark.py).

It checks:

- candidate sediment quality
- promotion policy stability
- recall correctness
- context binding
- repeated reproduction of the same intended top result

## Muscle memory rule

The schema is not complete unless memory can move through four operational stages:

1. `sediment` - raw event to candidate object
2. `promote` - candidate to verified object
3. `bind` - verified object influences planning or execution
4. `reproduce` - later similar cases reuse the memory correctly

Use [`METAFORGE_OS_MEMORY_MUSCLE_MEMORY.md`](./METAFORGE_OS_MEMORY_MUSCLE_MEMORY.md) and [`D:\codex\knowledge\memory_muscle_memory_four_stage_v1.json`](D:\codex\knowledge\memory_muscle_memory_four_stage_v1.json) as the operational definition of this loop.
