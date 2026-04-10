# GitHub Launch Post

## Short Version

I am open-sourcing **Orchestrator MVP**, a local-first multi-agent coding orchestrator for Windows plus WSL.

The main idea is simple: chat should be the interface, not the source of truth.

This project persists tasks, policy, project memory, reports, and escalations as local state, then routes work through a bounded planner and worker loop with explicit operator supervision.

Current MVP flow:

1. accept a development task
2. attach policy and project context
3. route it through planner and worker lanes
4. execute through local adapters
5. persist outputs and escalations for later review

The current version is intentionally scoped as an MVP. It is not an "autonomous AGI" project. It is a practical local orchestration layer designed to actually run, persist state, and stay inspectable.

If you try it, I would especially value feedback on routing quality, approval boundaries, and what durable state is worth keeping between runs.

## Long Version

I am publishing **Orchestrator MVP**, a local-first multi-agent coding orchestrator built for Windows plus WSL.

Most agent demos still treat the chat transcript as the system. This project takes the opposite approach:

- chat is the interface
- local state is the source of truth
- planning, routing, execution, reports, and escalations are persisted outside the transcript

The repository currently focuses on a bounded local delivery loop:

- a task is submitted through Codex control or the dispatch CLI
- shared policy and project memory are attached automatically
- a planner chooses a route and worker lane
- local execution happens through PowerShell, WSL, and other adapters
- reports, state, and escalations are written back into the local data layer

The result is a system that is easier to inspect, resume, and supervise than a pure chat-native workflow.

This is still an MVP. Some important pieces are still early, especially tighter routing trust, a stronger approval queue, and cleaner task-isolation boundaries. But the core loop is now present, runnable locally, and covered by the included QA checks.

If this direction is interesting to you, I would especially like feedback on three things:

1. how you would design a trustworthy approval model for local agent execution
2. which parts of agent state should be persisted versus recomputed
3. what would make a local-first orchestration layer genuinely useful in your workflow

## One-Line Summary

Local-first multi-agent coding orchestrator with persistent state and bounded automation.
