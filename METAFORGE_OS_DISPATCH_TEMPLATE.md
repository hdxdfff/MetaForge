# MetaForge OS Dispatch Template

Use this template when dispatching work through `D:\codex\factoryctl.cmd` or a compatible control shell.

## Dispatch contract

Every dispatch must specify all of the following:

- target branch or workspace
- scope boundary
- required artifact type
- validation method
- downgrade rule if direct implementation is unsafe
- return path for the final artifact
- whether the task is chore-only or requires CEO review
- task schema fields required by the throughput blueprint
- the verification level selected before execution

## Required dispatch fields

### 1. Scope

State the exact target.

Example:

`Operate only on D:\codex\generated\toy-os-demo`

### 2. Boundary

State what must not be touched.

Example:

`Do not modify control layer, factory runtime, or unrelated workspaces.`

### 3. Artifact

Require one concrete output.

Allowed outputs:

- patch
- patch proposal
- branch goal
- test report
- risk list
- documentation delta

### 4. Validation

Require one of:

- build steps
- test steps
- QEMU verification
- static verification with explicit limitation note

### 4b. Task schema

Queueable production tasks must also include:

- `task_type`
- `artifact_spec`
- `verification_level`
- `max_runtime_seconds`
- `retry_limit`
- `rollback_rule`

Tasks missing these fields are not valid production dispatches.

### 5. Downgrade rule

If implementation cannot be completed safely, emit:

- patch proposal
- or branch goal

### 6. Return path

Name the exact output file and destination workspace.

Example:

`Write the artifact to D:\codex\generated\toy-os-demo\TOYOS_PAGING_STAGE0_BRANCH_GOAL.md`

### 7. Control tier

State one of:

- `chore-only`: local small model may draft and format, but no product-impacting execution
- `ceo-review-required`: the control shell must review before execution or acceptance

## KPI enforcement

A dispatch is invalid unless it requires:

- a landing file or patch target
- a validation section
- a scoped boundary
- a concrete queue target or routing lane
- a bounded runtime

Outputs without validation do not count as VDU.
Outputs that only land in provider workspaces do not count as ToyOS delivery.

## ToyOS dispatch template

```text
Operate only on D:\codex\generated\toy-os-demo.
Do not modify the control layer, MetaForge OS runtime, provider workspaces, or unrelated repositories.
Task: <one bounded ToyOS goal>.
Required artifact: <patch | patch proposal | branch goal | test report | risk list>.
Validation: <build/test/QEMU/static review with limitations>.
Control tier: <chore-only | ceo-review-required>.
If safe implementation is not possible, downgrade to <patch proposal or branch goal> instead of broad design discussion.
Write the result to D:\codex\generated\toy-os-demo\<ARTIFACT_NAME>.md.
A result counts only if it returns to the ToyOS workspace with explicit validation notes.
```

## Suggested ToyOS lanes

- paging
- scheduler
- syscall
- filesystem
- ELF loader
- tests
- docs

## Operator rule

Prefer multiple bounded dispatches over one large prompt.
Target `15–45 min` first-result time per lane.
Use local-model chore routing for repetitive low-risk tasks and reserve the control shell for review and final execution approval.
