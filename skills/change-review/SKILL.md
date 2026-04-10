# Change Review

Use this skill when reviewing a patch, branch, or generated artifact for quality and delivery completeness.

## Goal

Find behavioural regressions, missing validation, and weak delivery claims before the change is treated as complete.

## Review order

1. Confirm the intended target workspace and artifact path.
2. Inspect the diff or changed files.
3. Look for broken contracts, unsafe assumptions, and skipped validation.
4. Check whether machine-readable evidence was refreshed when the change affects tracked reports.
5. State residual risks and missing tests explicitly.

## Focus areas

- mismatched delivery paths
- docs claiming behaviour that code does not implement
- controller bypasses and direct state edits
- broadened blast radius without broader validation
- stale generated reports

## D:\codex notes

- For operator-flow work, verify alignment with `D:\codex\agents\factory-operator.md`.
- For OpenCode workflow changes, verify alignment with `D:\codex\METAFORGE-OS-QUICKSTART.md` and `D:\codex\opencode.jsonc`.
- For ToyOS changes, ensure delivery still points back to `D:\codex\generated\toy-os-demo`.

## Required output

- findings ordered by severity
- open questions or assumptions
- validation gaps
- brief change summary
