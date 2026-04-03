# MetaForge Backups

This repository is a backup entry point for two separate project tracks.

## Project 1: MetaForge

- [Manifest asset](https://github.com/hdxdfff/MetaForge/releases/download/backup-codex-complete-plus-generated-v2-20260404-022752/codex-complete-plus-generated-v2-20260404-022752.manifest.json)
- [Archive asset](https://github.com/hdxdfff/MetaForge/releases/download/backup-codex-complete-plus-generated-v2-20260404-022752/codex-complete-plus-generated-v2-20260404-022752.zip)
- [Release page](https://github.com/hdxdfff/MetaForge/releases/tag/backup-codex-complete-plus-generated-v2-20260404-022752)

Scope:
- `generated/toy-os-demo`
- `orchestrator-mvp/factory/runtime/harness_runs`
- `orchestrator-mvp/data/harness_goals`
- `goals`

## Project 2: ToyOS project backup

- [Manifest file](backups/toyos-project-backup-20260404-023214.manifest.json)
- [Archive file](backups/toyos-project-backup-20260404-023214.zip)

Scope:
- ToyOS-specific runtime and delivery state
- Local project backup package created earlier on `2026-04-04`

## Restore path

1. Pick the project you want to restore.
2. Open that project's manifest.
3. Download its archive.
4. Extract into the target workspace.
5. Re-run validation for that project only.

## Notes

- The two backup tracks are intentionally separate.
- Do not treat the ToyOS backup as part of MetaForge.
- Do not treat the MetaForge backup as a ToyOS-only artifact.
