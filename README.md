# MetaForge Backups

This repository is a backup entry point for the MetaForge / ToyOS workspace.

## Latest backup package

- [Backup manifest](backups/toyos-project-backup-20260404-023214.manifest.json)
- [Backup archive](backups/toyos-project-backup-20260404-023214.zip)

## What is included

- `generated/toy-os-demo`
- `orchestrator-mvp/factory/runtime/harness_runs`
- `orchestrator-mvp/data/harness_goals`
- `goals`

## Snapshot summary

- Created: `2026-04-04T02:32:16.002675`
- Source root: `D:\codex`
- Files captured: `1588`
- Uncompressed size: `2,450,156 bytes`
- Archive size: `983,372 bytes`
- Approximate archive size: `1.0 MB`

## Verification

The manifest lists the included roots, sample entries, and the main status files captured in the snapshot.
Use the manifest first when you want to inspect scope before unpacking the archive.

## Restore path

1. Download the archive.
2. Open the manifest to verify the scope.
3. Extract the archive into the target workspace.
4. Rehydrate the ToyOS and orchestrator state from the extracted files.

## Notes

- This repository currently stores backup artifacts and the entry pages for them.
- For live development, use the local workspace rather than editing the archive directly.
