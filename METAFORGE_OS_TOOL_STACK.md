# MetaForge OS Tool Stack

This document defines the preferred human entry surface, control shell, execution layers, and final verification boundary for the local system.

## Canonical stack

- `OpenCode`: interaction entry
- `Goose`: control and dispatch executor
- `Aider`: short interactive coding entry
- `MetaForge`: core control layer
- `OpenHands` or `Plandex`: long-task execution layer
- `Codex`: development executor among the execution options
- `Continue`: PR inspection surface
- `Verification / Artifact`: final decision layer

## Operator CLI

`factoryctl` is the stable operator-facing CLI for direct communication with the system.
For a shorter operator-facing reference, see [METAFORGE_OS_CLI_QUICKSTART.md](D:/codex/METAFORGE_OS_CLI_QUICKSTART.md).

Recommended commands:

- `factoryctl.cmd health`
- `factoryctl.cmd logs`
- `factoryctl.cmd ops`
- `factoryctl.cmd status`
- `factoryctl.cmd verify`
- `factoryctl.cmd doctor`
- `factoryctl.cmd report`
- `factoryctl.cmd inbox`
- `factoryctl.cmd dispatch "<prompt>" [--precheck-only] [--confirm]`
- `factoryctl.cmd deploy "<target>"`
- `factoryctl.cmd rollback "<target>"`
- `factoryctl.cmd confirm deploy`
- `factoryctl.cmd dispatch "<prompt>" --precheck-only`
- `factoryctl.cmd route "<request>"`
- `factoryctl.cmd memory <status|integrity|quality|recall>`

Compatibility rule:

- Any legacy command such as `daemon-status`, `control-layer-status`, or `engineering-os-status` still passes through unchanged.
- Structured commands should be preferred for new operator workflows.

## Role boundaries

### Aider

- best for short interactive coding loops
- best for back-and-forth code edits
- should not be treated as the system of record

### OpenCode

- best for interactive intent capture and control requests
- should remain interaction-only
- should not directly mutate files or run shell commands

### Goose

- best for control-plane actions and dispatch
- best for registry reconciliation, script maintenance, and config/json/manifest fixes
- should not own long feature implementation

### OpenCode / Goose

- `OpenCode` is the front door
- `Goose` is the control and maintenance executor
- should mediate, not own, the truth source
- should delegate long work to MetaForge-managed execution layers

### MetaForge

- owns control state, routing policy, audit, and task identity
- decides what runs, where it runs, and what counts as completion
- must remain executor-agnostic

### OpenHands / Plandex

- best for long-running agentic tasks
- best for multi-step execution with persistent context
- should return artifacts, logs, and state updates

### Codex

- one of the primary development executors
- best for complex code changes, refactors, and multi-file implementation
- should be used as an executor, not as the control plane

### Continue

- best for PR inspection, local review, and change comprehension
- should inform review but not replace verification

### Verification / Artifact

- final pass/fail decision comes from evidence
- artifacts, tests, manifests, and logs are the source of truth
- executor self-claims do not count as completion

## Routing rule

Route work by task shape:

- short interactive edit -> `Aider`
- long agentic implementation -> `OpenHands` or `Plandex`
- controlled management and dispatch -> `Goose`
- interactive intent capture -> `OpenCode`
- code review and PR inspection -> `Continue`
- final acceptance -> `Verification / Artifact`

## Control rule

The system should never treat the tool name as the authority.

The authority is:

1. MetaForge control state
2. task contract
3. validation evidence
4. artifact ledger

## Usability rule

If a named tool is not installed on the current machine, the stack must fall back to the nearest available control surface and say so explicitly.

Current local fallback on this machine:

- `OpenCode` for control-shell actions
- `Codex` for control and executor orchestration
- `D:\codex\factoryctl.py` for control-plane commands

## Route command

Use the route command when you want the stack to choose a surface for a request:

```powershell
D:\codex\factoryctl.py tool-stack-route "review this pull request"
D:\codex\factoryctl.py tool-stack-route "fix this build error in the repository"
```
