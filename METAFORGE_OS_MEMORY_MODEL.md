# MetaForge OS Memory Model

This file defines the shared memory model for Codex multi-session development.

## Purpose

Make memory durable across dialogues so new sessions can start from the current system state instead of rebuilding context manually.

## Memory layers

### 1. Identity memory

Stable facts about what the system is:

- system identity
- mission
- operator surface
- role split
- hard constraints

### 2. State memory

Short-lived but high-signal operational facts:

- active task count
- active execution roots
- route drift count
- current CEO priority
- local-model availability
- shared dialogue session and message counts

### 3. Delivery memory

Work-in-progress and recent delivery facts:

- current lane work
- target workspaces
- pending outputs
- invalid delivery risks
- last accepted artifacts
- dialogue-linked workspace references

### 4. Decision memory

Recent judgments worth preserving across sessions:

- current contradiction
- chosen next action
- current guardrails
- current degradation policy
- recent dialogue decisions

### 5. Handoff memory

What a new dialogue needs to take over work immediately:

- lane hint
- authoritative workspace
- control tier
- required validation
- files to read first
- recent dialogue topics and constraints

### 6. Dialogue memory

Durable local conversation memory shared between Codex and MetaForge:

- raw session files under `D:\codex\knowledge\dialogue-memory\sessions`
- session index at `D:\codex\knowledge\dialogue-memory\session_index.json`
- shared summary at `D:\codex\orchestrator-mvp\data\dialogue_memory.json`

## Memory source rule

Prefer stable derived memory from:

- `D:\codex\orchestrator-mvp\data\memory_kernel.json`
- `D:\codex\orchestrator-mvp\data\context_kernel.json`
- `D:\codex\orchestrator-mvp\data\goal_memory.json`
- `D:\codex\orchestrator-mvp\data\dialogue_memory.json`
- `D:\codex\orchestrator-mvp\data\memory_objects.jsonl`
- `D:\codex\metaforge-self-status.ps1`
- `D:\codex\metaforge-ceo-status.ps1`

## Memory quality rule

Good memory is:

- compact
- cross-dialogue reusable
- explicit about uncertainty
- aligned with current system policy

## Memory muscle rule

Memory becomes operational only when it follows the four-stage loop described in [`METAFORGE_OS_MEMORY_MUSCLE_MEMORY.md`](./METAFORGE_OS_MEMORY_MUSCLE_MEMORY.md):

1. Sediment raw events into candidate objects.
2. Promote only structured, scoped, evidence-backed candidates.
3. Bind verified memory into live routing, verification, and continuity decisions.
4. Reproduce the learned behavior correctly in later similar tasks.

If memory does not change behavior, it is archive only.
If memory repeatedly changes behavior correctly, it is muscle memory.

Do not treat giant raw logs as first-class memory.

The fixed memory-muscle benchmark lives in [`D:\codex\knowledge\memory_muscle_benchmark_v1.json`](D:/codex/knowledge/memory_muscle_benchmark_v1.json) and is evaluated by [`D:\codex\orchestrator-mvp\tools\memory_muscle_benchmark.py`](D:/codex/orchestrator-mvp/tools/memory_muscle_benchmark.py).

## Multi-session rule

Every new dialogue should consume a shared memory snapshot before planning.
Every main dialogue should refresh that snapshot after major routing, lane, or delivery changes.
Every Codex dialogue that matters operationally should be synced into local memory through `D:\codex\factoryctl.cmd dialogue-sync` or `D:\codex\metaforge-dialogue-assetize.ps1`.
