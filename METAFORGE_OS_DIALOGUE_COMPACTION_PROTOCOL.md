# MetaForge OS Dialogue Compaction Protocol

This file defines how Codex dialogues should avoid slowdown when a thread becomes too long.

## Problem

A very long dialogue accumulates too much transient context.
That increases latency, raises prompt noise, and weakens decision quality.

## Principle

Do not keep one dialogue alive forever.
When a thread becomes long, preserve memory and handoff, then continue work in a fresh dialogue lane.

## Trigger signals

Compact and hand off when any of the following happens:

- the dialogue is visibly slow or lagging
- repeated answers require re-reading too much prior context
- the active focus has narrowed to one bounded lane
- the main contradiction is already stable and recorded
- a new worker dialogue can take over with a compact snapshot

## Compaction output

A compaction step should produce:

- current contradiction
- current CEO priority
- lane type
- authoritative workspace
- control tier
- required validation
- active tasks and roots
- files to read first
- next bounded action

## Required artifacts

Preferred artifacts:

- `METAFORGE_OS_ACTIVE_DIALOGUE_SNAPSHOT.json`
- `METAFORGE_OS_ACTIVE_DIALOGUE_HANDOFF.md`

## Rule

After compaction:

- keep the current dialogue as CEO lane if needed
- move bounded work into a fresh dialogue
- let the new dialogue start from the snapshot, not from the entire old conversation

## Quality rule

A good dialogue compaction is:

- short
- operational
- lane-specific
- explicit about validation and authority
