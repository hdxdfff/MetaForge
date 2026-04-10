# P2 Sandbox Audit Report

## Target Files
- D:\codex\orchestrator-mvp\data\autonomy_control_plane_summary.md
- D:\codex\orchestrator-mvp\data\autonomy_control_plane.json

## Smallest Gap
The sandbox gate is intentionally closed by the industrial operations budget.

## Gate State
- control_json_allow_p2_sandbox: False
- industrial_allow_p2_sandbox: False
- budget_gate: sandbox_closed

## Patch Plan
- Keep the P2 sandbox section in the summary markdown.
- Keep allow_p2_sandbox aligned with the industrial operations gate.
- Refresh the control-plane summary after any budget change.

## Validation Commands
- Get-Content "D:\codex\orchestrator-mvp\data\autonomy_control_plane_summary.md"
- python D:\codex\orchestrator-mvp\tools\autonomy_control_plane.py

## Residual Risk
Sandbox lane remains intentionally narrow and budgeted.
