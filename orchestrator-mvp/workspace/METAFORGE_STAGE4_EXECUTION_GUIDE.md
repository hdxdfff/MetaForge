# MetaForge Stage-4 Execution Guide

Scope: only `D:\codex\orchestrator-mvp`

Purpose: guide the factory to complete MetaForge Stage-4 without drifting into ToyOS, generic web-product work, or parallel architecture expansion.

## Single active line

Only one line is active now:

1. Self-Improvement Engine

The following lines are frozen until Self-Improvement reaches the merge-ready threshold:

- Safety Guardrail: supporting prerequisite only
- Research Engine: frozen
- Evolution System: frozen

## Hard rule

Do not run the three architecture lines in parallel.

MetaForge must not actively expand Research Engine or Evolution System until Self-Improvement can complete the full closed loop:

1. detect bug or quality failure
2. generate bounded patch
3. run validation automatically
4. mark merge-ready or merge through approved gate

If this loop is not working, Research and Evolution are considered non-primary and must not consume the main execution lane.

## Why

Without a working Self-Improvement loop:

- Research Engine becomes a knowledge accumulator without delivery
- Evolution System becomes variant churn without reliable upgrade mechanics
- the system remains below Stage-4 regardless of how many side modules exist

## Stage-4 success metric

There is only one decisive metric for Stage-4 entry:

MetaForge can automatically complete:

- find bug
- generate patch
- pass tests
- merge code

If that loop is real, MetaForge enters Stage-4 AI organization.

## Factory routing rule

For the active lane:

- route only Self-Improvement work as primary execution
- treat Safety Guardrail as a supporting constraint, not a parallel roadmap
- freeze Research and Evolution to report-only mode
- avoid routing to `webapp_generation` provider workspaces
- keep outputs inside `D:\codex\orchestrator-mvp` or `D:\codex\orchestrator-mvp\workspace`
- treat all core-mutating work as `ceo-review-required` unless an explicit approved patch policy says otherwise

## Core safety rule

Core Modules Immutable.

The following areas must not be automatically mutated unless routed through `approved_patch` or equivalent explicit approval:

- control layer
- scheduler and orchestration control path
- state system and persistent state schema

Initial protected module families:

- `app/`
- `runtime/`
- `state/`
- control-critical parts of `tools/`

## Non-touch boundaries

Do not change:

- `D:\codex\generated\toy-os-demo`
- `D:\codex\opencode-control.ps1`
- `D:\codex\factoryctl.cmd`
- approval/security policies through implicit self-mutation
- destructive git behavior

## Active files

Primary active goal:

- `D:\codex\orchestrator-mvp\workspace\METAFORGE_SELF_IMPROVEMENT_ENGINE_BRANCH_GOAL.md`

Supporting constraint:

- `D:\codex\orchestrator-mvp\workspace\METAFORGE_SAFETY_GUARDRAIL_BRANCH_GOAL.md`

Frozen until Self-Improvement succeeds:

- `D:\codex\orchestrator-mvp\workspace\METAFORGE_RESEARCH_ENGINE_BRANCH_GOAL.md`
- `D:\codex\orchestrator-mvp\workspace\METAFORGE_EVOLUTION_SYSTEM_BRANCH_GOAL.md`

## First-result rule

The only acceptable primary outputs now are:

- bounded patch proposal
- bounded patch candidate
- automated validation result
- merge handoff record
- blocker report that explains why automatic patch-test-merge failed

Do not count broad architecture discussion as progress.

## Success condition

MetaForge remains pre-Stage-4 until Self-Improvement can demonstrate automatic patch generation, automatic testing, and automatic merge readiness on real defects.
