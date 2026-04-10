# MetaForge OS Chore Dispatch Template

Use this template for repetitive low-risk work that should be drafted by the local small-model layer and reviewed by OpenCode only when needed.

## Contract

Every chore dispatch must include:

- exact target workspace
- explicit non-touch boundaries
- one artifact file
- one lightweight validation method
- control tier
- return path

## Control tiers

- `chore-only`: local model may complete draft/report output with no code-impacting action
- `ceo-review-required`: local model drafts, OpenCode must review before acceptance or execution

## Preferred chore artifacts

- status report
- risk list
- inventory summary
- test-plan draft
- dispatch draft
- route-drift report
- operator digest

## Chore template

```text
Operate only on <TARGET_WORKSPACE>.
Do not modify control layer, runtime internals, unrelated repositories, or product code unless explicitly allowed.
Task: <one repetitive bounded task>.
Required artifact: <status report | risk list | inventory summary | test-plan draft | operator digest>.
Validation: <static review against state files | log cross-check | file presence check>.
Control tier: <chore-only | ceo-review-required>.
If direct implementation is unsafe or ambiguous, downgrade to a report instead of modifying code.
Write the result to <EXACT_OUTPUT_PATH>.
A result counts only if it lands in the specified workspace with explicit validation notes.
```

## Examples

- route-drift digest for ToyOS
- pending task triage report
- QEMU log condensation
- syscall inventory summary
- multi-dialogue lane status digest
