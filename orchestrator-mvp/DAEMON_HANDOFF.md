# Factory Daemon Handoff

## Goal

Leave MetaForge in a state where the control loop keeps running without an interactive Codex session.

## Runtime Model

- `start-factory-daemon.ps1` starts the daemon in the background.
- `ensure-factory-daemon.ps1` checks health, honors startup grace, and restarts the daemon if the tracked process is missing or the tick is stale.
- `install-factory-daemon-task.ps1` installs the watchdog task and tries to install an `ONLOGON` start task. The task actions now launch `pythonw.exe` through a hidden PowerShell launcher that uses `CREATE_NO_WINDOW`.

## Recommended Handoff Path

1. Start one daemon instance:
   - `powershell -ExecutionPolicy Bypass -File D:\codex\orchestrator-mvp\start-factory-daemon.ps1`
2. Verify the daemon is ticking:
   - `D:\codex\factoryctl.cmd daemon-status`
   - `D:\codex\factoryctl.cmd self-model`
3. Install persistent hosting:
   - `powershell -ExecutionPolicy Bypass -File D:\codex\orchestrator-mvp\install-factory-daemon-task.ps1`
4. Verify watchdog output:
   - `powershell -ExecutionPolicy Bypass -File D:\codex\orchestrator-mvp\ensure-factory-daemon.ps1`

## Acceptance Signals

Handoff is complete when these are all true:

- `data/factory_daemon_state.json` shows a live `pid` or startup grace handoff in progress
- `data/factory_daemon_state.json` shows increasing `cycle`
- `data/factory_daemon_state.json` has a recent `last_tick_at`
- `data/factory_daemon_state.json` has non-null `last_self_model_goal`
- `data/status_cache.json.self_model` is present
- `data/self_model_runtime.json.state.health` is not `degraded`

## Primary Evidence Files

- `D:\codex\orchestrator-mvp\data\factory_daemon_state.json`
- `D:\codex\orchestrator-mvp\data\status_cache.json`
- `D:\codex\orchestrator-mvp\data\self_model_runtime.json`
- `D:\codex\orchestrator-mvp\data\factory_daemon.log`

## Failure Semantics

`ensure-factory-daemon.ps1` will restart the daemon when any of the following are true:

- the tracked pid is gone
- the daemon state file is missing
- `last_tick_at` is missing after startup grace
- `last_tick_at` is older than the configured staleness window

## Current Autonomous Scope

The daemon now continuously runs:

- factory maintenance
- control layer refresh
- self model cycle
- self model summary writeback into daemon state and status cache

The remaining work is not recovery plumbing. It is steady-state execution expansion.
