# VM Runtime Migration Acceptance

Date: 2026-04-10
Workspace: `D:\codex`
Authority root: `/srv/orchestrator-mvp`

## Goal

Confirm that the VMware Ubuntu VM is the only live runtime root and that the Windows host has been reduced to sync, backup, read-only observation, and manual recovery trigger duties.

## Scope Completed

- VM is the only live runtime root for daemon, control layer, verification, release, and ToyOS evidence.
- Windows host local daemon entrypoints are frozen.
- Windows host scheduled-task installers that could recreate active runtime control are frozen.
- Windows host observer commands read VM live state instead of stale local snapshots.
- The authority contract is present on both host and VM.

## Authority Contract

Host source:
- `D:\codex\knowledge\vm_runtime_authority_contract.json`

VM source:
- `/srv/orchestrator-mvp/knowledge/vm_runtime_authority_contract.json`

Contract summary:
- `authority_root = /srv/orchestrator-mvp`
- `host_role = [sync, backup, read status, manual recovery trigger]`
- Host must not become the live daemon host or authority for live state.

## Frozen Host Entrypoints

Daemon and watchdog:
- `D:\codex\orchestrator-mvp\start-factory-daemon.ps1`
- `D:\codex\orchestrator-mvp\run-factory-daemon.ps1`
- `D:\codex\orchestrator-mvp\ensure-factory-daemon.ps1`
- `D:\codex\orchestrator-mvp\install-factory-daemon-task.ps1`
- `D:\codex\orchestrator-mvp\install-factory-daemon-startup.ps1`

Scheduled task installers:
- `D:\codex\orchestrator-mvp\install-release-manager-task.ps1`
- `D:\codex\orchestrator-mvp\install-p2-sandbox-task-generator.ps1`
- `D:\codex\orchestrator-mvp\install-keepalive-task.ps1`
- `D:\codex\orchestrator-mvp\install-industrial-readiness-task.ps1`
- `D:\codex\orchestrator-mvp\install-industrial-operations-task.ps1`
- `D:\codex\orchestrator-mvp\install-historical-debt-archive-task.ps1`
- `D:\codex\orchestrator-mvp\install-continuity-metrics-task.ps1`
- `D:\codex\orchestrator-mvp\install-budget-suppression-task.ps1`
- `D:\codex\orchestrator-mvp\install-autonomy-control-plane-task.ps1`
- `D:\codex\orchestrator-mvp\install-stage5-tasks.ps1`
- `D:\codex\orchestrator-mvp\install-stage5-amplifiers.ps1`

Expected behavior:
- frozen installers return `status = "frozen"`
- frozen daemon/watchdog entrypoints return `status = "observer_only_host"`

## Acceptance Evidence

### 1. VM runtime is live

Command:

```powershell
D:\codex\factoryctl.cmd daemon-status
```

Observed:
- `source = live`
- `execution_root = vm_ssh_primary`
- `daemon.status = running`
- `pid = 14335`
- `cycle = 330`
- `stale = false`

### 2. Control layer is live and healthy

Command:

```powershell
D:\codex\factoryctl.cmd control-layer-status --refresh
```

Observed:
- `status = stable`
- `control_policy.execution = active`
- `quality_system.status = promote`
- `quality_system.overall_score = 0.9479`
- `signal_dashboard.Release Readiness = ready`
- `release_operations.status = pass`
- `release_train_status = ready`

### 3. Engineering OS is live and healthy

Command:

```powershell
D:\codex\factoryctl.cmd engineering-os-status --refresh
```

Observed:
- `engineering_os.status = pass`
- `verification_engine.status = pass`
- `release_gate_status = pass`
- runtime dashboard = `healthy`
- release dashboard = `ready`

### 4. Autonomy remains confirmed on VM live state

Command:

```powershell
D:\codex\factoryctl.cmd autonomy-score --refresh
```

Observed:
- `stage = stage4_confirmed`
- `score = 0.8528`
- `control_layer_status = stable`
- `quality_status = promote`
- `stable_autonomy = true`
- `needs_more_soak = false`
- `needs_operator_attention = false`

### 5. ToyOS evidence exists in VM

Command:

```powershell
E:\codex\vmctl.cmd ssh -CommandString "bash -lc 'test -d /srv/orchestrator-mvp/generated/toy-os-demo && echo toyos_artifacts_present'"
```

Observed:
- `toyos_artifacts_present`

### 6. Authority contract exists in VM

Command:

```powershell
E:\codex\vmctl.cmd ssh -CommandString "bash -lc 'test -f /srv/orchestrator-mvp/knowledge/vm_runtime_authority_contract.json && echo vm_acceptance_ok'"
```

Observed:
- `vm_acceptance_ok`

## Result

Accepted.

The software migration objective is complete:
- VM is the only live runtime root.
- Host is no longer an autonomous runtime host.
- Host remains available for sync, backup, observation, and manual recovery trigger only.

## Residual Risk

- This acceptance does not include a physical host-disconnect soak test.
- `daemon-status` may still show transient recovery-oriented fields inside `last_result`; authoritative refreshed control and autonomy views are healthy and ready.
- Recovery trigger still exists from host by design, but it no longer restores host authority; it only dispatches to the VM runtime path.

## Changed

- `D:\codex\orchestrator-mvp\tools\codex_control.py`
- `D:\codex\factoryctl.py`
- `D:\codex\knowledge\vm_runtime_authority_contract.json`
- `D:\codex\orchestrator-mvp\start-factory-daemon.ps1`
- `D:\codex\orchestrator-mvp\run-factory-daemon.ps1`
- `D:\codex\orchestrator-mvp\ensure-factory-daemon.ps1`
- `D:\codex\orchestrator-mvp\install-factory-daemon-task.ps1`
- `D:\codex\orchestrator-mvp\install-factory-daemon-startup.ps1`
- `D:\codex\orchestrator-mvp\install-release-manager-task.ps1`
- `D:\codex\orchestrator-mvp\install-p2-sandbox-task-generator.ps1`
- `D:\codex\orchestrator-mvp\install-keepalive-task.ps1`
- `D:\codex\orchestrator-mvp\install-industrial-readiness-task.ps1`
- `D:\codex\orchestrator-mvp\install-industrial-operations-task.ps1`
- `D:\codex\orchestrator-mvp\install-historical-debt-archive-task.ps1`
- `D:\codex\orchestrator-mvp\install-continuity-metrics-task.ps1`
- `D:\codex\orchestrator-mvp\install-budget-suppression-task.ps1`
- `D:\codex\orchestrator-mvp\install-autonomy-control-plane-task.ps1`
- `D:\codex\orchestrator-mvp\install-stage5-tasks.ps1`
- `D:\codex\orchestrator-mvp\install-stage5-amplifiers.ps1`
- `D:\codex\vm-entry-root\vm-common.ps1`
- `D:\codex\vm-entry-root\vm-ssh.ps1`
- `D:\codex\vm-entry-root\vm-bridge.ps1`

## Artifact

- `D:\codex\generated\vm-runtime-migration-acceptance-2026-04-10.md`
