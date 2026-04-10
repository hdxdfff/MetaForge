# MetaForge OS Dialogue Handoff Pack

This file defines what a new dialogue should receive when taking over work.

## Handoff payload

A handoff should contain:

- lane type
- authoritative workspace
- current contradiction
- current CEO priority
- control tier
- validation requirement
- startup files
- startup command

## Default handoff examples

### CEO lane

- lane: `ceo-lane`
- workspace: `D:\codex`
- focus: routing integrity, lane arbitration, bounded dispatch approval
- control tier: `ceo-review-required`

### Chore lane

- lane: `chore-lane`
- workspace: `D:\codex`
- focus: summaries, reports, digests, inventories
- control tier: `chore-only`

### Product lane

- lane: `product-lane`
- workspace: `D:\codex\generated\toy-os-demo`
- focus: bounded ToyOS delivery
- control tier: `ceo-review-required` unless report-only

### Research lane

- lane: `research-lane`
- workspace: `D:\codex`
- focus: routing, KPI, policy, memory, self-improvement
- control tier: `ceo-review-required`

## Startup rule

Every new dialogue should read the shared memory snapshot first, then map itself into one lane.
