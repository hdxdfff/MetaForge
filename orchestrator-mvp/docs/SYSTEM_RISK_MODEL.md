# System Risk Model

This workspace uses a parallel risk branch alongside the main daemon/control/verification path.

Flow:

`signals -> risk evaluator -> policy gate -> safe repair executor -> semantic verifier -> incident ledger`

Entry points:

- `tools/risk_scan.py` runs the full branch.
- `tools/incident_report.py` summarizes the ledger.
- `tools/drill_runner.py` runs the built-in drills.
- `app/main.py` exposes `/api/risk/status`, `/api/risk/scan`, and `/api/incidents`.

Risk classes covered by the first pass:

- `runtime.queue_starvation`
- `runtime.false_liveness`
- `verification.misalignment`
- `routing.model_degradation`
- `config.drift`
- `continuity.distortion`
- `release.promotion_mismatch`
- `repair.secondary_damage`

The branch is intentionally bounded:

- the engine only classifies risk
- the policy gate decides if repair is allowed
- the executor only runs whitelisted actions
- the verifier checks semantic recovery, not just process liveness
- the ledger records every incident transition

