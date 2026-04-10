# Repo Onboard

Use this skill when entering a new repository, subsystem, or unfamiliar workspace area.

## Goal

Produce a fast orientation pack that lets later tasks execute without guessing.

## Inputs

- Target workspace path
- Optional focus area such as frontend, backend, kernel, controller, or tooling

## Procedure

1. Inspect the top-level layout and identify the likely runtime, package manager, and test surface.
2. Read only the minimum operator docs needed to find start, test, lint, and build entry points.
3. Identify the key mutating directories and any files that act as control planes.
4. Detect whether the workspace is documentation-only, tooling-only, or code-bearing.
5. Note blocked capabilities such as missing `rg`, missing package managers, or controller-only mutation rules.

## Required output

Return a compact orientation report with:

- workspace purpose
- stack or runtime
- preferred start commands
- preferred validation commands
- high-risk directories
- likely delivery directory
- open blockers

## D:\codex notes

- Prefer `D:\codex\factoryctl.cmd` and `D:\codex\opencode-control.ps1` when the target is orchestrated state.
- Treat `D:\codex\knowledge` and `D:\codex\goals` as durable state, not scratch space.
- If the task points at ToyOS, deliveries must resolve under `D:\codex\generated\toy-os-demo`.
