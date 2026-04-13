# MetaForge OS Chore Queue Policy

This file defines which work should default to the local small model layer and when work must escalate to the control shell or MetaForge decision layer.

## Purpose

Use cheap local cognition for repetitive bounded labor while keeping final control in the MetaForge control layer.

## Default task routing

Send a task to the local small model first if all of the following are true:

- the task is repetitive
- the task is low risk
- the task has a clear schema or output shape
- the result can be checked against symbolic state or simple rules
- failure does not directly damage product code or control integrity

## Chore queue

The following tasks belong to the local-model chore queue by default:

- state summarization
- log condensation
- task tagging and triage
- dispatch draft generation
- report skeleton generation
- checklist completion
- duplicate detection in task queues
- verification note formatting
- inbox digest generation
- recurring status snapshots

## Control shell escalation gate

A task must escalate to the control shell before execution if any of the following are true:

- it changes product code
- it changes control or routing behavior
- it changes workspace boundaries
- it changes KPI or safety policy
- it involves unresolved ambiguity
- it involves repeated failures
- it can trigger invalid delivery to be counted as success
- it spans multiple dialogue lanes with competing priorities

## Control review rule

The control shell should treat local-model outputs as drafts unless the task is explicitly marked as chore-only.

The control shell must review before:

- dispatch
- patch application
- branch-goal promotion
- invalid-delivery classification
- route-repair decisions

## ToyOS-specific rule

For ToyOS, the local model may help with:

- test-plan drafting
- syscall inventory summaries
- route-drift reports
- QEMU log condensation

The local model must not be the final authority for:

- code changes in `D:\codex\generated\toy-os-demo`
- workspace target selection
- acceptance of provider-only output

## Throughput rule

If the local model can clear repetitive queue load, keep the control shell focused on:

- controller judgment
- routing integrity
- bounded implementation approval
- high-value architecture decisions
