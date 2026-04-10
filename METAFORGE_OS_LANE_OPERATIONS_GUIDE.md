# MetaForge OS Lane Operations Guide

This file summarizes how to use lane-based multi-session development in the local workspace.

## Core files

- `D:\codex\dialogue_lanes.json`
- `D:\codex\METAFORGE_OS_LANE_REGISTRY.md`
- `D:\codex\METAFORGE_OS_LANE_WORKBOARD.json`
- `D:\codex\lane-assets\*.json`
- `D:\codex\lane-assets\*.md`

## Core commands

```powershell
D:\codex\metaforge-memory-snapshot.ps1
D:\codex\metaforge-lane-asset-pack.ps1
D:\codex\metaforge-open-lane.ps1 -Lane product-lane
D:\codex\metaforge-open-lane.ps1 -Lane research-lane
D:\codex\metaforge-lane-status.ps1
D:\codex\metaforge-dialogue-assetize.ps1
D:\codex\metaforge-dialogue-compact.ps1
```

## Recommended use

### Main dialogue

Use as `ceo-lane`.
Responsibilities:

- lane arbitration
- route integrity
- bounded execution approval
- conflict resolution

### Product dialogue

Use `product-lane` when advancing ToyOS or other bounded product work.

### Research dialogue

Use `research-lane` for routing, KPI, memory, and self-improvement topics.

### Chore dialogue

Use `chore-lane` for low-risk summaries, reports, inventories, and digests.

### Throughput execution

Use `research-lane` for throughput policy, queue design, KPI structure, and saturation rules.
Use `chore-lane` for rollout checklists, policy deltas, and report refreshes that support the high-throughput blueprint.
The current execution reference is:

- `D:\codex\METAFORGE_OS_HIGH_THROUGHPUT_BLUEPRINT.md`

## Long-thread handling

If a dialogue grows slow:

1. run `metaforge-dialogue-assetize.ps1`
2. run `metaforge-dialogue-compact.ps1`
3. open the needed lane with `metaforge-open-lane.ps1`
4. continue work in a fresh dialogue from the lane asset

## Current limitation

Lane organization is working locally, but target-workspace routing is still not enforced by the underlying factory runtime.
So lane assets are operationally useful, but they do not yet repair provider-workspace drift by themselves.
