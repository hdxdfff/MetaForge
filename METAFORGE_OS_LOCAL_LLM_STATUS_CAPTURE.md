# MetaForge OS Local LLM Status Capture

This file defines how MetaForge OS should use a local model to summarize system state.

## Goal

Use a local model to convert raw self/state/world snapshots into a compact operational judgment.
Treat the local model as a cheap repetitive-work engine, not the top authority.

## Inputs

The local model should read:

- self summary
- CEO summary
- self-improvement summary

## Output

The output should answer:

- what is the top contradiction
- what is the current operating priority
- what should be executed now
- what should be deferred
- whether the system should degrade or scale

The output may also support:

- repeated status refreshes
- queue triage
- dispatch draft generation
- operator digest generation

## Runtime strategy

Preferred:

- local `node-llama-cpp` or another local GGUF runtime

Fallback:

- structured rules using the same inputs

## Rule

A local model summary is useful only if it preserves the same hard constraints as the symbolic state:

- target workspace integrity
- verification-first delivery
- no provider-only output counted as success

`OpenCode` should review and mediate these outputs before they are treated as CEO decisions or dispatch actions.

## Current deployment mode

The local model path and runtime are now present in the workspace.
Current practice is:

- let the local model handle cheap repeated state interpretation
- let `OpenCode` act as the temporary CEO and policy gate
- fall back to structured rules if local inference is unavailable or too slow
