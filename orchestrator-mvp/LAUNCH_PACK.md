# Launch Pack

## Recommended Public Positioning

Primary name:
- Orchestrator MVP

Primary one-line description:
- Local-first multi-agent coding orchestrator with persistent state, bounded automation, and Codex-first supervision.

Alternative subtitles:
- A local software-delivery loop for planning, execution, and escalation
- Multi-agent coding orchestration for Windows plus WSL
- Persistent task, policy, and project memory for local AI-assisted development

## README Hero Copy

Suggested repo header:

```md
# Orchestrator MVP

Local-first multi-agent coding orchestrator with persistent state and bounded automation.
```

Suggested short pitch:

```md
Orchestrator MVP routes development tasks through a local planner, cheap worker lanes, and execution adapters, then persists policy, memory, reports, and escalations outside the chat transcript.
```

## GitHub About Section

Use one of these:

- Local-first multi-agent coding orchestrator with persistent state and bounded automation.
- Multi-agent software orchestration for Windows plus WSL, with shared memory and explicit escalation.
- Codex-supervised local delivery loop for planning, execution, and task persistence.

Topics to consider:

- multi-agent
- ai-agents
- orchestration
- developer-tools
- fastapi
- wsl
- automation
- local-first
- llm
- codex

## Suggested Launch Post

### GitHub release note style

```md
Orchestrator MVP is a local-first multi-agent coding orchestrator for Windows plus WSL.

This version focuses on a bounded execution loop:
- accept a task
- attach policy and project memory
- route through planner and worker lanes
- run local execution adapters
- persist state, reports, and escalations

The current repo is intentionally positioned as an MVP. The goal is not "autonomous AGI", but a practical local orchestration layer with explicit state and operator supervision.
```

### Hacker News

Title options:
- Show HN: Orchestrator MVP, a local-first multi-agent coding orchestrator
- Show HN: A local-first multi-agent orchestrator for coding tasks
- Show HN: Multi-agent coding orchestration with persistent state and bounded automation

Body:

```text
I built a local-first multi-agent coding orchestrator for Windows plus WSL.

The core idea is simple: chat should be the interface, not the source of truth. Tasks, policy, project memory, reports, and escalations are persisted under a local state layer, and the operator reviews the system through Codex-first control commands.

Current MVP loop:
1. submit a task
2. attach policy and project context
3. plan and route it
4. execute through local adapters and worker lanes
5. persist outputs and escalations for later review

The repo is still early, but the current version can run locally and pass the included QA checks.

I would especially value feedback on:
- routing and worker selection
- what a trustworthy approval queue should look like
- how much state should be persisted vs recomputed
```

### X / Twitter

Post 1:

```text
Built an MVP for a local-first multi-agent coding orchestrator.

Instead of treating chat as the system, it persists tasks, policy, project memory, reports, and escalations as local state.

Windows + WSL, FastAPI control plane, Codex-first supervision.
```

Post 2:

```text
New repo: Orchestrator MVP

A bounded local delivery loop for AI-assisted development:
- plan
- route
- execute
- persist
- escalate only when needed

Not an AGI claim. Just a practical orchestration layer that can actually run locally.
```

Post 3:

```text
I think one missing piece in agent systems is durable local state.

This project experiments with a multi-agent coding orchestrator where chat is the interface, but policy, memory, tasks, and escalations live outside the transcript.
```

## Suggested Screenshot Order

For the GitHub README or release thread, use this order:

1. status command output
2. architecture diagram
3. task persistence example
4. smoke demo report

## Recommended Launch Sequence

1. push the verified README and architecture docs
2. capture one clean status screenshot
3. capture one smoke-demo screenshot or short GIF
4. publish the GitHub repo
5. post to Hacker News and X using the copy above
6. collect feedback before expanding the vision language

## What Not To Lead With

Avoid leading the first public post with:

- AI civilization
- self-evolving civilization
- autonomous research organization
- infinite branch architecture

Those ideas can stay in the roadmap, but they raise the abstraction level too early. The MVP is strongest when framed as a practical local orchestration system.
