ToyOS verification task: unify the evidence chain into one final contract.

Scope:
- Align `build-report.json`, `test-report.json`, `execution-report.json`, and `score-report.json`.
- Define one final success/failure contract that does not conflict across reports.
- Make the evidence story consistent for review, demos, and funding narratives.

Expected delivery:
- Updated evidence definitions or report templates under `D:\codex\generated\toy-os-demo`.
- A short note describing the final evidence contract and precedence rules.
- Refreshed machine-readable evidence showing the unified contract was applied.

Acceptance:
- Build, test, execution, and score evidence all point to the same final outcome.
- No report contradicts another on success criteria.
- The final evidence contract is easy to audit and reuse.

Constraints:
- Keep the first version narrow and explicit.
- Do not invent a broad new framework if a thin contract layer is enough.
- Prefer machine-readable alignment over prose-only explanation.
