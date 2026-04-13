# OpenCode Quickstart

OpenCode is now the preferred interaction surface for the local MetaForge OS.

## Preferred start

```powershell
powershell -ExecutionPolicy Bypass -File D:\codex\opencode-factory.ps1
```

or

```powershell
D:\codex\opencode-factory.cmd
```

## Direct start

```powershell
powershell -ExecutionPolicy Bypass -File D:\codex\opencode.ps1
```

or

```powershell
D:\codex\opencode.cmd
```

## Recommended first checks inside the workspace

Prefer the Python-backed controller entrypoint so host execution policy is not part of the control path:

```powershell
D:\codex\factoryctl.cmd daemon-status
D:\codex\factoryctl.cmd control-layer-status
D:\codex\factoryctl.cmd engineering-os-status
D:\codex\factoryctl.cmd lab-status
```

Python also works directly:

```powershell
D:\codex\tools\python311-embed\python.exe D:\codex\factoryctl.py daemon-status
```

## Control flow

1. Inspect status first.
2. Open a control session only for mutating actions.
3. Use controller-backed commands instead of manual JSON inspection.
4. Keep OpenCode focused on interaction and operator workflow.

## Startup options

If you want to skip the pre-launch status block:

```powershell
powershell -ExecutionPolicy Bypass -File D:\codex\opencode-factory.ps1 -NoStatus
```

## Notes

- DeepSeek access now works through the local wrapper.
- If OpenCode reports a database I/O error again, rotate and recreate the dedicated OpenCode state roots under `D:\codex\oi-state-opencode` or `D:\codex\oi-state-opencode-fast`.
- OpenCode has been moved to a small interaction workspace so it no longer snapshots the entire `D:\codex` tree.
- New OpenCode state roots are `D:\codex\oi-state-opencode` and `D:\codex\oi-state-opencode-fast`.
- `D:\codex\factoryctl.cmd` is the preferred control entrypoint.

## Natural command bridge

For common operator actions, use:

```powershell
powershell -ExecutionPolicy Bypass -File D:\codex\opencode-control.ps1 "查看状态"
powershell -ExecutionPolicy Bypass -File D:\codex\opencode-control.ps1 "查看实验室"
powershell -ExecutionPolicy Bypass -File D:\codex\opencode-control.ps1 "查看自治评分"
```

Mutating actions require a control-session token:

```powershell
powershell -ExecutionPolicy Bypass -File D:\codex\opencode-control.ps1 "开始控制模式"
powershell -ExecutionPolicy Bypass -File D:\codex\opencode-control.ps1 "派发任务 加强 agent orchestration" -SessionToken <token>
```
