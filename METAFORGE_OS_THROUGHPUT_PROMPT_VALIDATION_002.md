# Throughput Prompt Validation 002

## Canonical audit-task output schema

### Coder output

- `target_files`
- `smallest_gap`
- `patch_plan`
- `validation_commands`
- `residual_risk`

### Reviewer output

- `verdict`
- `evidence_checked`
- `validation_status`
- `regression_risks`
- `follow_up_patch`
- `next_action`

## Valid output example

An audit task is valid when the response contains every required marker for the worker role and states a bounded next action.

## Invalid output examples

- Generic summary without concrete files
- Missing `validation_commands`
- Missing `next_action`
- Review text that only restates the prompt

## Validation notes

- The worker-side schema guard now rejects audit-task responses that do not contain the required structured markers before the task is marked complete.
- The guard is scoped to research/governance audit work so the rest of the worker flow remains unchanged.

