# MetaForge OS

This workspace is organized around the MetaForge OS project, with a split between the human-facing entry surface and the persistent control plane.

## Role

- Treat `Aider` as the primary interactive coding surface.
- Treat `OpenCode` or `Goose` as the control shell.
- Treat `MetaForge` as the project umbrella name, not a runtime component.
- Treat the control layer as the persistent control layer.
- Treat `OpenHands` or `Plandex` as long-task execution layers.
- Treat `Continue` as the PR inspection surface.
- Treat the factory runtime as the persistent execution system.
- Treat local small models as the repetitive-work layer for cheap summarization, classification, extraction, and status chores.

## Source of truth

Use controller-backed commands and persistent state instead of ad-hoc guesses.

- Controller: `D:\codex\factoryctl.cmd`
- Control shell: `D:\codex\opencode.cmd`
- Runtime state: `D:\codex\orchestrator-mvp\data`
- Architecture notes: `D:\codex\METAFORGE_OS_ARCHITECTURE.md`
- Security framework: `D:\codex\METAFORGE_OS_SECURITY_FRAMEWORK.md`
- State notes: `D:\codex\METAFORGE_OS_STATE.md`
- Self-awareness layer: `D:\codex\METAFORGE_OS_SELF_AWARENESS_LAYER.md`
- Identity model: `D:\codex\METAFORGE_OS_SYSTEM_IDENTITY.json`
- State model: `D:\codex\METAFORGE_OS_STATE_MODEL.md`
- World model: `D:\codex\METAFORGE_OS_WORLD_MODEL.json`
- CEO agent spec: `D:\codex\METAFORGE_OS_CEO_AGENT.md`
- Metacognition protocol: `D:\codex\METAFORGE_OS_METACOGNITION_PROTOCOL.md`
- Self-improvement loop: `D:\codex\METAFORGE_OS_SELF_IMPROVEMENT_LOOP.md`
- Role split: `D:\codex\METAFORGE_OS_ROLE_SPLIT.md`
- Tool stack: `D:\codex\METAFORGE_OS_TOOL_STACK.md`

## KPI Policy

Follow the system KPI policy in `D:\codex\METAFORGE_OS_KPI_POLICY.md`.
Use the formal ToyOS productivity specification as the active operating policy.
The primary objective is verifiable throughput under sustained workload, not raw code volume.

## Self Model Rule

Before high-value planning or dispatch, read the self-awareness layer and preserve answers to:

- who am I
- what am I doing
- why am I doing it
- what happens if premium reasoning is unavailable

Use `D:\codex\metaforge-self-status.ps1` as the local self/state/world summary entrypoint.
Use `D:\codex\metaforge-ceo-status.ps1` as the local CEO decision snapshot.
Use `D:\codex\metaforge-improvement-status.ps1` as the local self-improvement priority snapshot.

## Default operating mode

- Cheap-first execution.
- Local model first for repetitive or low-risk cognition.
- `OpenCode` mediates between operator intent, local-model outputs, and persistent runtime actions when used as the control shell.
- Safety policy is enforced at the control layer, not delegated to the model.
- Premium reasoning only for:
  - architecture conflicts
  - repeated failures
  - security boundaries
  - irreversible actions

## Preferred commands

```powershell
D:\codex\metaforge-self-status.ps1
D:\codex\metaforge-ceo-status.ps1
D:\codex\metaforge-improvement-status.ps1
D:\codex\metaforge-local-llm-status.ps1
D:\codex\factoryctl.cmd status
D:\codex\factoryctl.cmd daemon-status
D:\codex\factoryctl.cmd control-layer-status
D:\codex\factoryctl.cmd engineering-os-status
D:\codex\factoryctl.cmd lab-status
D:\codex\factoryctl.cmd organization-workboard
D:\codex\factoryctl.py tool-stack-status
D:\codex\factoryctl.py tool-stack-route "fix this build error in the repository"
```
