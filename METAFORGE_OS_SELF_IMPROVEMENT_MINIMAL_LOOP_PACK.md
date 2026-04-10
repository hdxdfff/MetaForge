# Self-Improvement Minimal Closed Loop Pack

## Purpose

This pack turns MetaForge OS self-awareness into an operational improvement loop.

## Included units

- self summary
- CEO summary
- improvement summary
- local LLM status capture
- fallback structured reasoning

## Required entrypoints

- `D:\codex\metaforge-self-status.ps1`
- `D:\codex\metaforge-ceo-status.ps1`
- `D:\codex\metaforge-improvement-status.ps1`
- `D:\codex\metaforge-local-llm-status.ps1`

## Loop

1. Read self state.
2. Read CEO state.
3. Read improvement state.
4. Run local LLM summarizer if ready.
5. Otherwise run fallback structured summary.
6. Select one bounded improvement target.
7. Execute only if it does not weaken delivery integrity.

## Current observed outcome

The current top contradiction remains route drift.
Therefore the closed loop should favor:

- routing guard
- workspace lock
- lane-aware dispatch

before scaling automation breadth.
