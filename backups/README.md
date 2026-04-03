# Backup Index

## Available backups

| Package | Manifest | Archive | Created |
| --- | --- | --- | --- |
| ToyOS project backup | [manifest](toyos-project-backup-20260404-023214.manifest.json) | [zip](toyos-project-backup-20260404-023214.zip) | `2026-04-04T02:32:16.002675` |

## Scope

- Source root: `D:\codex`
- Captured roots:
  - `generated/toy-os-demo`
  - `orchestrator-mvp/factory/runtime/harness_runs`
  - `orchestrator-mvp/data/harness_goals`
  - `goals`

## Suggested restore order

1. Manifest first.
2. Archive second.
3. Reconcile runtime status files after extraction.
4. Re-run the ToyOS validation flow.

## Integrity cues

The manifest records:

- file count
- compressed and uncompressed sizes
- sampled entries
- excluded name substrings
- selected runtime status files
