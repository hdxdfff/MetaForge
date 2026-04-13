# Backup and Publish Workflow

This workflow keeps workspace mutations backed by two durable copies:

- a local snapshot in `D:\codex\backups\backup_<timestamp>`
- a GitHub commit pushed from the current branch

## Entry point

Use the wrapper:

```powershell
D:\codex\backup-and-publish.cmd snapshot
D:\codex\backup-and-publish.cmd publish --message "your message here"
```

The wrapper calls `D:\codex\tools\workspace_backup.py`.

## What it does

- Reads the current git status from `D:\codex`
- Copies every changed code or documentation file into a timestamped backup folder
- Writes a `manifest.json` next to the copied files
- For `publish`, stages the workspace changes, commits them, and pushes the current branch to `origin`

## When to use it

- After any code change
- After any documentation change
- Before handing off a substantial controller, runtime, or workflow mutation

## Operator rule

- Do not claim a mutation is complete until the local snapshot exists and the GitHub push has succeeded.
- If publish fails, keep the local snapshot and report the failure path explicitly.

## Validation

- Confirm the snapshot directory exists
- Confirm `manifest.json` exists in that directory
- Confirm `git status --short` is clean after publish
- Confirm the branch upstream exists on GitHub
