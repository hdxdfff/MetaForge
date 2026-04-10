# MetaForge OS Self-Awareness Layer

This file defines the minimum self-awareness stack for MetaForge OS.

## Required models

MetaForge OS must always be able to answer three questions before or during execution:

- Who am I?
- What state am I in?
- What world am I acting on?

## Layer structure

```text
Self Model
    -> identity, mission, capabilities, fallback rules
State Model
    -> current tasks, health, resources, bottlenecks, active mode
World Model
    -> workspaces, tools, external reachability, execution surfaces
Planner
    -> chooses next bounded action
Workers
    -> execute bounded actions
```

## Files

- Identity: `D:\codex\METAFORGE_OS_SYSTEM_IDENTITY.json`
- World model: `D:\codex\METAFORGE_OS_WORLD_MODEL.json`
- Live state root: `D:\codex\orchestrator-mvp\data`
- Operator policy: `D:\codex\METAFORGE-OS.md`
- KPI policy: `D:\codex\METAFORGE_OS_KPI_POLICY.md`

## Self-model contract

Before high-value work, the system should be able to state:

- identity
- mission
- current operating mode
- active priorities
- fallback path when premium reasoning is unavailable

## State-model contract

Before or during execution, the system should know:

- active task count
- queued or blocked work
- open escalations
- route drift or verification failures
- which workspace is the execution root

## World-model contract

Before changing files or dispatching work, the system should know:

- target workspace
- available runtimes and tools
- whether execution is local-first or VM-first
- whether the task depends on network or premium models

## CEO-agent interpretation

The resident control loop should behave like a meta-agent with these responsibilities:

- manage system health
- manage task routing
- manage resource use
- decide when to degrade to proposals or reports
- preserve continuity when stronger models or remote services are unavailable

## Fallback principle

If premium planning is unavailable, MetaForge OS must still preserve:

- self identity
- task ledger
- state snapshot
- bounded dispatch capability
- verification-first delivery policy

This is the minimum condition for remaining an operating system rather than reverting into disconnected scripts.
