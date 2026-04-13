# MetaForge OS CLI Quickstart

`factoryctl` is the stable operator CLI for MetaForge system communication.

## Entry Point

- Main launcher: `D:\codex\factoryctl.cmd`
- Python implementation: `D:\codex\factoryctl.py`
- Runtime: most control actions execute through the VMware Ubuntu VM

## Read Commands

- `factoryctl.cmd status --human`
- `factoryctl.cmd health --human`
- `factoryctl.cmd ops --human`
- `factoryctl.cmd verify --human`
- `factoryctl.cmd doctor --human`
- `factoryctl.cmd report --human`
- `factoryctl.cmd inbox --open-only`
- `factoryctl.cmd route "<request>" --human`
- `factoryctl.cmd memory summary --human`

## Precheck and Confirmation

- `factoryctl.cmd dispatch "<prompt>" --precheck-only --human`
- `factoryctl.cmd dispatch "<prompt>" --require-confirm --human`
- `factoryctl.cmd confirm deploy --human`
- `factoryctl.cmd confirm rollback --human`

## Controlled Changes

- `factoryctl.cmd deploy "<target>" --dry-run --human`
- `factoryctl.cmd rollback "<target>" --dry-run --human`
- `factoryctl.cmd dispatch "<prompt>" --confirm --human`

## Recommended Flow

1. Check state: `status`, `health`, `ops`, `report`
2. Check routing: `route "<request>"`
3. Run precheck: `dispatch "<prompt>" --precheck-only`
4. Confirm readiness: `confirm deploy` or `confirm rollback`
5. Submit only when ready: `dispatch "<prompt>" --confirm`

## Output Rules

- Default output is machine-readable when possible
- Add `--human` for compact summaries
- `dispatch --precheck-only` never submits work
- `deploy` and `rollback` are preview-first; final submission should go through controlled `dispatch`

## Permissions

- Read-only commands usually work without extra setup
- Submit commands may require an operator session
- To pass a session token, use:
  - `factoryctl.cmd --session-token <token> <command> ...`

## Examples

- `factoryctl.cmd status --human`
- `factoryctl.cmd dispatch "smoke test" --precheck-only --human`
- `factoryctl.cmd deploy toy-os-demo --dry-run --human --workspace D:\codex\generated\toy-os-demo`
- `factoryctl.cmd rollback toy-os-demo --dry-run --human`
- `factoryctl.cmd memory recall "dialogue sync"`

## Constraints

- Do not bypass the control layer and edit runtime state directly
- Do not treat "started" as "done"
- Use state, validation, and artifacts as the source of truth
- For permission errors, check session and control policy first

