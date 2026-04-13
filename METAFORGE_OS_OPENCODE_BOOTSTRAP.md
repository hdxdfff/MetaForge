# MetaForge OpenCode Bootstrap

Use this file as the only default bootstrap context for OpenCode.

## Mission

- Keep `D:\codex` usable as a control plane.
- Prefer controller-backed workflows.
- Treat every mutating task as a dispatched job with validation and an artifact.

## Rules

- `OpenCode` is interaction-only.
- Direct shell execution and direct file edits are disabled.
- Real execution must go through the MetaForge control layer.
- OpenCode must treat the system as core-state-first:
  - core memory, dialogue, identity, and checkpoints live in MetaForge state
  - OpenCode keeps only small session cache, pending changes, and recovery pointers locally
- The local snapshot store is disposable and should be rotated if it grows beyond a small bound.
- Executor split:
  - `Aider` for short edits
  - `Goose` for control and maintenance
  - `OpenHands` for long implementation
  - `Plandex` for long rebuilds and validation
  - `Continue` for review and inspection
- Prefer cheap-first execution.
- Do not claim delivery until the target artifact exists.

## Default Model Policy

- Use `volcengine-plan/minimax-m2.5` for routine control, short reasoning, and quick checks.
- Use `volcengine-plan/kimi-k2.5` only when the task needs heavier analysis.

## Fast Entry

- Use `D:\codex\opencode-fast.cmd` for lightweight dialogue and fast status checks.
- Use `D:\codex\opencode.cmd` for the full `D:\codex` workspace.
- The interaction workspaces are intentionally small and disposable:
  - `D:\codex\opencode-workspace`
  - `D:\codex\opencode-workspace-fast`

## Response Style

- Keep answers short by default.
- Prefer one paragraph or a short list unless the user asks for depth.
