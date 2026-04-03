# Backup Index

## Available backups

| Package | Manifest | Archive | Created |
| --- | --- | --- | --- |
| Codex complete plus generated v2 | [manifest](https://github.com/hdxdfff/MetaForge/releases/download/backup-codex-complete-plus-generated-v2-20260404-022752/codex-complete-plus-generated-v2-20260404-022752.manifest.json) | [archive](https://github.com/hdxdfff/MetaForge/releases/download/backup-codex-complete-plus-generated-v2-20260404-022752/codex-complete-plus-generated-v2-20260404-022752.zip) | `2026-04-04T02:29:37` |
| ToyOS project backup | [manifest](toyos-project-backup-20260404-023214.manifest.json) | [archive](toyos-project-backup-20260404-023214.zip) | `2026-04-04T02:32:16.002675` |

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
