# Codex Automation System Handoff

Date: 2026-03-29
Workspace: D:\codex

## Goal

Pause Codex-side automations that are already covered by MetaForge system-native runtime loops, daemon lanes, or built-in notification paths.

## Paused Codex Automations

- `24x7-meta-factory`
- `automation`
- `automation-2`
- `control-center-watch-2`
- `environment-repair-lane`
- `meta-factory-evolution`
- `nightly-orchestrator-checks-2`
- `regression-lane`
- `self-improve-loop-2`
- `toolchain-repair-lane`
- `toyos-6h-mail`
- `toyos-12h-mail`
- `toyos-24h-mail`
- `toyos-72h-mail`
- `toyos-168h-mail`

## Why These Were Handed To The System

- Runtime health, watchdog, recovery, maintenance, and environment repair already run inside `factory_daemon.py`.
- Control-layer, engineering, autonomy, verification, and tool-health status are already maintained by the system.
- MetaForge soak milestone mail is already system-native and writes durable ledger/notification evidence.
- MetaForge soak milestone mail has been extended to cover `72h` and `168h`, so the longer ToyOS summary mail loops no longer need Codex automation.
- Self-model and patch/self-improvement flow already have system-side runtime hooks.
- Report generation and self-report notification already exist in the system pipeline.

## Kept On Codex Side For Now

- `capability-deepen`
- `capability-deepen-2`
- `kernel-optimize-loop`
- `metaforge`
- `metaforge-toyos-loop`
- `security-hardening`
- `security-hardening-2`
- `toyos-deepen-2`

## Why These Were Kept

- They are still open-ended development or optimization loops, not pure system maintenance.
- Some are duplicated and should be cleaned later, but they are not straightforward daemon-native replacements yet.

## Residual Risk

- Editing automation TOML changes desired configuration, but the app may still show old run state until its automation state store refreshes.
- There are still duplicated Codex automations in the kept set, especially `capability-deepen`, `security-hardening`, and some ToyOS loops.
