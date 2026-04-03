# ToyOS project backup

This entry page covers the second backup track in the repository.

## Scope

- `generated/toy-os-demo`
- ToyOS-specific build, runtime, and delivery artifacts

## Assets

- Manifest: [backups/toyos-project-backup-20260404-023214.manifest.json](toyos-project-backup-20260404-023214.manifest.json)
- Archive: [backups/toyos-project-backup-20260404-023214.zip](toyos-project-backup-20260404-023214.zip)

## Restore order

1. Restore the manifest.
2. Restore the archive.
3. Rehydrate ToyOS delivery state from the recovered package.

## Boundary

This track is intentionally separate from MetaForge.
