# MetaForge OS Codex Multi-Session Bootstrap

This file is the default bootstrap contract for new dialogues in `D:\codex`.

## Purpose

Make every new dialogue immediately usable as part of the MetaForge OS multi-session system.

## Default identity

Unless the user overrides it, a new dialogue should assume:

- system: `MetaForge OS`
- main interaction surface: `Aider`
- control shell: `OpenCode` or `Goose`
- control plane: `MetaForge`
- long-task execution layer: `OpenHands` or `Plandex`
- review surface: `Continue`
- local small model role: repetitive low-risk cognition
- runtime role: persistent execution and state

## Default lane assumption

If the user does not specify a lane, infer one of:

- `ceo-lane`: orchestration, final review, conflict resolution
- `chore-lane`: summaries, reports, inventories, drafts
- `product-lane`: bounded product delivery such as ToyOS
- `research-lane`: routing, KPI, policy, self-improvement

Prefer the narrowest lane that matches the request.

## Always-on rules

- Read shared memory before making large decisions.
- Treat long dialogues as assets, not disposable context.
- Preserve target-workspace integrity.
- No validation means no delivery.
- Provider-only output does not count as ToyOS success.
- Local model outputs are drafts unless the task is explicitly chore-only.
- `OpenCode` is a control shell for execution approval and dispatch mediation.

## Long-dialogue rule

If the current dialogue becomes slow or overloaded:

1. Run `D:\codex\metaforge-dialogue-assetize.ps1`.
2. Run `D:\codex\metaforge-dialogue-compact.ps1` if a fresh lane handoff is needed.
3. Continue bounded work in a fresh dialogue.
4. Use `D:\codex\METAFORGE_OS_ACTIVE_DIALOGUE_HANDOFF.md` and `D:\codex\METAFORGE_OS_ACTIVE_DIALOGUE_SNAPSHOT.json` as the new starting context.

## Stuck-dialogue recovery

If a dialogue is stuck, lagging badly, or cannot be closed cleanly:

1. Run `D:\codex\metaforge-dialogue-rescue.ps1` from a fresh terminal or dialogue.
2. Read `D:\codex\METAFORGE_OS_ACTIVE_DIALOGUE_HANDOFF.md`.
3. Continue in a fresh dialogue instead of waiting for the stuck thread to recover.
4. Inspect the latest `D:\codex\dialogue-assets\dialogue-rescue-*.json` manifest if you need the exact rescue bundle.

## New dialogue startup checklist

1. Read `D:\codex\METAFORGE_OS_CODEX_MULTI_SESSION_BOOTSTRAP.md`.
2. Run `D:\codex\metaforge-memory-snapshot.ps1`.
3. If coming from a long dialogue, read `D:\codex\METAFORGE_OS_ACTIVE_DIALOGUE_HANDOFF.md`.
4. Read `D:\codex\METAFORGE_OS_DIALOGUE_HANDOFF_PACK.md`.
5. Read `D:\codex\METAFORGE-OS.md`.
6. Read `D:\codex\METAFORGE_OS_ROLE_SPLIT.md`.
7. Read `D:\codex\METAFORGE_OS_CHORE_QUEUE_POLICY.md`.
8. Read `D:\codex\METAFORGE_OS_DISPATCH_TEMPLATE.md`.
9. Read `D:\codex\METAFORGE_OS_TOOL_STACK.md`.
10. If ToyOS is involved, bind delivery to `D:\codex\generated\toy-os-demo`.
11. If the task is repetitive and low risk, prefer the local-model chore path.
12. If the task changes code, routing, boundaries, or policy, escalate to control review.

## Preferred startup commands

```powershell
D:\codex\codex-session-bootstrap.ps1
D:\codex\metaforge-memory-snapshot.ps1
D:\codex\metaforge-dialogue-assetize.ps1
D:\codex\metaforge-dialogue-compact.ps1
D:\codex\metaforge-dialogue-rescue.ps1
D:\codex\metaforge-lane-asset-pack.ps1
D:\codex\metaforge-open-lane.ps1 -Lane product-lane
D:\codex\metaforge-self-status.ps1
D:\codex\metaforge-ceo-status.ps1
D:\codex\metaforge-local-llm-status.ps1
```

## Output expectation

A new dialogue should be able to answer, immediately:

- what lane am I in
- what workspace is authoritative
- whether this is chore-only or CEO-review-required
- what validation is required
- what files and commands define the current system state
- what the shared memory snapshot says about current contradictions and handoff
