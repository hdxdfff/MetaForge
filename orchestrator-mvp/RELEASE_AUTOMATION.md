# Release Automation

This repository now includes a release manager automation flow for later product releases.

## Purpose

The release manager acts as an operations gate for release readiness. It combines:

- local QA status
- release operations readiness
- candidate release records
- optional release-train advancement when gates are green

## Commands

Read release readiness:

```powershell
python tools\release_manager.py
```

Or use the PowerShell wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File .\run-release-manager.ps1
```

Attempt to advance the release train when all gates are green:

```powershell
python tools\release_manager.py --advance
```

Or:

```powershell
powershell -ExecutionPolicy Bypass -File .\run-release-manager.ps1 -Advance
```

## Scheduled Operations

Install a recurring release-check task every 30 minutes:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-release-manager-task.ps1
```

Install with a custom interval:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-release-manager-task.ps1 -IntervalMinutes 15
```

Install an auto-advance schedule only if you trust the release gates:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-release-manager-task.ps1 -Advance
```

## Output

The script writes a normalized summary to:

- `data/release_manager_status.json`

The payload includes:

- overall status
- QA result
- release operations snapshot
- latest candidate summary
- blockers
- suggested actions
- release train result

## Release Gates

A release is blocked when any of these are true:

- local QA fails
- runtime is not healthy
- verification is not ready
- control layer is not stable
- blocked patches are present

## Intended Ops Flow

1. run `python tools\release_manager.py`
2. inspect blockers and suggested actions
3. clear blockers
4. run `python tools\release_manager.py --advance`
5. record or publish the release candidate

## API Surface

The FastAPI app exposes:

- `GET /api/release-manager`
- `POST /api/release-manager/run`

Use `POST /api/release-manager/run` with `{ "advance": true }` only when you want the release train to promote eligible candidates.
