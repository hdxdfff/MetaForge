# ToyOS Foundation Loop

This file defines the minimum project-side foundation layer for sustained ToyOS automation.

## Purpose

Connect ToyOS delivery work to the existing MetaForge self-improvement, goal, and knowledge systems without introducing a second orchestration stack.

## Order of operations

1. Refresh issue intake with `python D:\codex\tools\bug_discovery\toyos_bug_snapshot.py`.
2. Read `D:\codex\knowledge\discovered_issues.json`.
3. Select the top open issue that maps to an active goal in `D:\codex\goals\active_goals.json`.
4. Implement one bounded ToyOS change inside `D:\codex\generated\toy-os-demo`.
5. Rebuild validation evidence and update knowledge patterns if a new lesson appears.

## Files

- Issue intake: `D:\codex\knowledge\discovered_issues.json`
- Active goals: `D:\codex\goals\active_goals.json`
- Completed goals: `D:\codex\goals\completed_goals.json`
- Bug memory: `D:\codex\knowledge\bug_patterns.json`
- Patch memory: `D:\codex\knowledge\patch_patterns.json`
- Validation memory: `D:\codex\knowledge\validation_patterns.json`

## Operating rules

- Keep ToyOS execution bounded to `D:\codex\generated\toy-os-demo`.
- Prefer stable-path preservation over broad kernel churn.
- Treat new findings as data that must feed the next loop, not as one-off chat output.
- Do not promote experimental success to stable-path success without separate validation.
