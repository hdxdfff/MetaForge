# MetaForge OS Executor Division

This document freezes the current executor split for the local system.

## Principle

- `OpenCode` is interaction-only.
- Mutating work must be routed through the control layer.
- Executors do the work; control surfaces decide where work goes.
- Verification still requires evidence, not self-claims.

## Final division

| Surface | Role | Good for | Not for |
| --- | --- | --- | --- |
| `OpenCode` | Interaction entry | Chatting, intent capture, task framing, control requests | Direct shell, direct file mutation, long-running execution |
| `Goose` | Control and dispatch executor | Control-plane actions, routing, registry maintenance, JSON/config/manifest fixes, operational scripts | Large feature builds, long multi-file implementation |
| `Aider` | Short edit executor | Small interactive code edits, fast local fixes, doc patches, narrow refactors | Full-stack orchestration, control-plane dispatch |
| `OpenHands` | Long implementation executor | Long-running agentic implementation, multi-step work, artifact-producing tasks | Fast chat loop, control-plane ownership |

## Working rule

Use this mapping in order:

1. Capture intent in `OpenCode` or the control surface.
2. Route the task through MetaForge control state.
3. Dispatch to `Goose`, `Aider`, or `OpenHands` based on task shape.
4. Validate with logs, tests, or artifacts.

## Practical guidance

- Use `OpenCode` when you want a fast interactive front door with no direct execution.
- Use `Goose` when the task touches control state, routing, or maintenance glue.
- Use `Aider` when the change is small and local.
- Use `OpenHands` when the task needs sustained execution and artifact output.

## Reference files

- [OpenCode entry summary](/D:/codex/OPENCODE-CLINE.md)
- [Tool stack overview](/D:/codex/METAFORGE_OS_TOOL_STACK.md)
- [Executor routing contract](/D:/codex/orchestrator-mvp/contracts/tool_stack.json)
