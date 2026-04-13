# Bugfix Loop

Use this skill when the task is to diagnose and fix a defect, regression, or failed check.

## Goal

Move from evidence to patch with the smallest safe change set, then leave behind validation evidence.

## Procedure

1. Capture the current failure signal.
2. Find the narrowest file set that can explain the failure.
3. Patch only the files needed to remove the defect.
4. Run the cheapest validation that can falsify the fix.
5. Escalate to broader validation only if the cheap check fails or the change crosses subsystem boundaries.
6. Record new recurring evidence in `D:\codex\knowledge` when the bug reveals a durable pattern.

## Validation ladder

Run the first applicable rung, then climb only as needed:

1. Static read of the affected code path
2. Existing targeted script or test
3. Local build or compile step
4. Workspace-specific smoke test
5. Broader regression sweep

## D:\codex notes

- For ToyOS regression surfacing, start with `D:\codex\tools\bug_discovery\toyos_bug_snapshot.py` when the issue is architectural or recurring.
- Prefer machine-readable reports in `D:\codex\knowledge` over prose-only bug notes.
- Do not close the loop without naming the residual risk.

## Required output

- failure signal
- changed files
- validation executed
- updated evidence path
- residual risk
