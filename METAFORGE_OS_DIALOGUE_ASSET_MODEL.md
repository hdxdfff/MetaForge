# MetaForge OS Dialogue Asset Model

This file defines how long dialogues become durable system assets instead of disposable context.

## Principle

A long dialogue is not just temporary chat history.
It contains reusable system value.

## Asset layers

### 1. Raw archive asset

Keep the full original long-form material when available.
Purpose:

- preserve reasoning trace
- preserve exact user constraints
- preserve failure and recovery chronology
- preserve Codex or operator message history when exported

### 2. Distilled memory asset

Compact, cross-dialogue reusable knowledge extracted from the long dialogue.
Purpose:

- preserve stable system facts
- preserve persistent decisions
- preserve constraints and priorities

### 3. Handoff asset

Operational startup package for a fresh dialogue.
Purpose:

- lane takeover
- bounded execution continuity
- fast startup without replaying the whole thread

### 4. Shared dialogue ledger

Operator-facing local storage that bridges Codex and MetaForge.
Purpose:

- keep per-session dialogue summaries in `D:\codex\knowledge\dialogue-memory\sessions`
- aggregate reusable dialogue facts into `D:\codex\orchestrator-mvp\data\dialogue_memory.json`
- expose those facts through memory snapshots and context packages

## Asset value types

A long dialogue may contain:

- identity decisions
- architecture decisions
- routing and guardrail discoveries
- productivity policy
- failure patterns
- validated operator workflows
- project-specific constraints

## Asset quality rule

An asset is good if it is:

- reusable
- scoped
- explicit
- aligned with current system policy
- small enough for repeated loading

## Required outputs for long-thread assetization

Preferred outputs:

- archive note
- distilled memory snapshot
- active handoff file
- shared dialogue ledger entry
- lane-specific handoff if needed

## Rule

Do not force every new dialogue to consume the raw archive.
Consume the distilled asset by default.
Open the raw archive only when the compressed asset is insufficient.
Use `D:\codex\metaforge-dialogue-assetize.ps1` or `D:\codex\factoryctl.cmd dialogue-sync` to register dialogue assets into the shared ledger.
