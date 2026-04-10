# MetaForge OS Parallel Dialogue Development Pack

This file defines the minimal operating pack for using multiple dialogues as parallel development lanes.

## Lane types

- `ceo-lane`: operator-facing main dialogue, final authority for bounded execution
- `chore-lane`: repetitive low-risk work, local-model assisted
- `product-lane`: product-specific work such as ToyOS
- `research-lane`: architecture, routing, KPI, and self-improvement analysis

## Lane rule

Each dialogue lane must declare:

- lane id
- target workspace
- scope boundary
- control tier
- merge policy

## Default split

- main dialogue: `ceo-lane`
- auxiliary dialogues for summaries/reports: `chore-lane`
- ToyOS implementation dialogue: `product-lane`
- MetaForge routing/self-improvement dialogue: `research-lane`

## Promotion rule

No lane may promote its own output to accepted delivery without CEO review if:

- it changes product code
- it changes routing behavior
- it changes workspace boundaries
- it resolves conflicts across lanes

## Minimal rollout

1. Keep this dialogue as the CEO lane.
2. Route repetitive status/report work to chore lanes.
3. Route ToyOS bounded product tasks to product lanes.
4. Route architecture and policy work to research lanes.
5. Promote only after CEO review.
