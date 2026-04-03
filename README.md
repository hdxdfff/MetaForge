# MetaForge Backups

This repository is a backup entry point for the MetaForge / ToyOS workspace.

## Latest backup package

- [Backup manifest asset](https://github.com/hdxdfff/MetaForge/releases/download/backup-codex-complete-plus-generated-v2-20260404-022752/codex-complete-plus-generated-v2-20260404-022752.manifest.json)
- [Backup archive asset](https://github.com/hdxdfff/MetaForge/releases/download/backup-codex-complete-plus-generated-v2-20260404-022752/codex-complete-plus-generated-v2-20260404-022752.zip)
- [Release page](https://github.com/hdxdfff/MetaForge/releases/tag/backup-codex-complete-plus-generated-v2-20260404-022752)

## What is included

- `generated/toy-os-demo`
- `orchestrator-mvp/factory/runtime/harness_runs`
- `orchestrator-mvp/data/harness_goals`
- `goals`

## Snapshot summary

- Created: `2026-04-04T02:29:37`
- Source root: `D:\codex`
- Files captured: `1588`
- Uncompressed size: `2,450,156 bytes`
- Archive size: `990,125,817 bytes`
- Approximate archive size: `944.5 MB`

## Verification

The manifest lists the included roots, sample entries, and the main status files captured in the snapshot.
Use the manifest first when you want to inspect scope before unpacking the archive.

## Restore path

1. Download the archive asset from the release page.
2. Open the manifest to verify the scope.
3. Extract the archive into the target workspace.
4. Rehydrate the ToyOS and orchestrator state from the extracted files.

## Notes

- This repository stores the manifest and archive as release assets because the archive is too large for a normal repository contents upload.
- The earlier ToyOS-specific backup remains available as an archived entry.
