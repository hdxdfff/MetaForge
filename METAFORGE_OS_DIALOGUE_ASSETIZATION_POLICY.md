# MetaForge OS Dialogue Assetization Policy

This file defines how to preserve long dialogues as system assets.

## Goal

Turn long dialogues into durable operating knowledge without dragging their full transient context into every new session.

## Assetization flow

1. Preserve a compact archive note.
2. Refresh shared memory.
3. Refresh active handoff.
4. Optionally emit lane-specific handoff.

## Minimum archive note fields

- archive time
- main contradiction
- CEO priority
- key decisions
- key constraints
- current risks
- next bounded action

## Minimum memory refresh fields

- identity continuity
- route drift state
- active execution roots
- authoritative workspace
- current guardrails

## Minimum handoff fields

- lane hint
- control tier
- required validation
- startup files
- startup command

## Retrieval rule

When a new dialogue starts:

- load the shared memory asset first
- load the active handoff second
- read the archive note only if deeper historical detail is required

## Compaction rule

If the current dialogue is still the CEO lane, keep it alive after assetization only for arbitration.
Move implementation or report work into a fresh lane dialogue.
