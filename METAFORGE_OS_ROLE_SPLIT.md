# MetaForge OS Role Split

This file defines the working split between interactive entry surfaces, control shells, executors, and the persistent control plane.

## Layering

- Aider: primary interactive coding surface
- OpenCode or Goose: control shell
- MetaForge: persistent control layer
- OpenHands or Plandex: long-task execution layer
- Continue: PR inspection surface
- Factory runtime: persistent execution and state layer
- Local small model: repetitive labor layer

## Local small model responsibilities

Use the local model for work that is cheap, frequent, and bounded:

- state summarization
- log triage
- task classification
- dispatch draft generation
- patch/report formatting
- checklist completion
- repetitive document updates

The local model should not be trusted as the final authority for:

- architecture direction changes
- safety boundary changes
- workspace reinterpretation
- irreversible execution

## Control shell responsibilities

OpenCode or Goose act as the control shell.

It should:

- interpret operator intent
- translate commands into MetaForge control actions
- validate local-model output against system policy
- decide whether to execute, degrade, or escalate
- preserve identity, state, and world-model continuity
- prevent route drift and invalid delivery from being treated as success

## Factory runtime responsibilities

The runtime should:

- execute bounded work
- persist task and controller state
- expose telemetry for CEO review
- provide dispatch, queue, and health surfaces

## Decision rule

Default chain:

1. Local model produces a cheap first-pass judgment.
2. OpenCode validates the judgment against hard constraints.
3. Runtime executes only bounded approved actions.

## Hard constraints

- Target workspace integrity cannot be relaxed by a local model.
- Verification-first delivery cannot be relaxed by a local model.
- Provider-only output is not a valid success condition for ToyOS.
