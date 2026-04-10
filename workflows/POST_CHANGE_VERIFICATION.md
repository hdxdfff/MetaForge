# Post-Change Verification

Default checklist for changes made inside `D:\codex`.

## Purpose

Ensure every completed task leaves behind a verification trail that matches the cost and risk of the change.

## Baseline checklist

1. Confirm the exact files changed and the intended delivery path.
2. Run the cheapest relevant validation command or script.
3. If the change touches controller behavior, rerun the relevant `factoryctl` status command.
4. If the change affects a generated artifact, refresh that artifact or report.
5. Summarize what was validated and what remains unverified.

## Recommended commands

For operator-state or controller-facing changes:

```powershell
D:\codex\factoryctl.cmd daemon-status
D:\codex\factoryctl.cmd control-layer-status
D:\codex\factoryctl.cmd engineering-os-status
```

For lab or autonomy changes:

```powershell
D:\codex\factoryctl.cmd lab-status
D:\codex\factoryctl.cmd autonomy-score
```

For ToyOS issue tracking refresh:

```powershell
D:\codex\tools\python311-embed\python.exe D:\codex\tools\bug_discovery\toyos_bug_snapshot.py
```

## Escalation rule

- Start with the minimum check that can fail fast.
- Expand validation when the change crosses subsystem boundaries, alters orchestration behavior, or updates delivery promises.

## Output template

- `Changed:` exact files or directories touched
- `Validated:` command or evidence path
- `Artifact:` output path, if any
- `Residual risk:` what still was not exercised
