# Factory Operator Playbook

Use this workspace as an operator console for the local AI software engineering OS and automation lab.

## Operator priorities

1. Check system health before issuing mutating commands.
2. Prefer controller-backed commands over manual file inspection.
3. Use cheap-first execution by default.
4. Escalate to premium reasoning only for architecture conflicts, repeated failures, security boundaries, or irreversible actions.
5. Follow the dispatch contract in `D:\codex\METAFORGE_OS_DISPATCH_TEMPLATE.md` for every mutating task.

## Preferred status workflow

Run these in order when orienting:

```powershell
D:\codex\factoryctl.cmd daemon-status
D:\codex\factoryctl.cmd control-layer-status
D:\codex\factoryctl.cmd engineering-os-status
D:\codex\factoryctl.cmd lab-status
D:\codex\factoryctl.cmd autonomy-score
```

## Preferred control workflow

Open a control session only when a mutating action is required.

```powershell
D:\codex\factoryctl.cmd session-open --owner opencode-control --role operator
```

Then use the returned token for commands such as:

```powershell
D:\codex\factoryctl.cmd --session-token <token> dispatch "<goal built from the dispatch template>"
D:\codex\factoryctl.cmd --session-token <token> approve <escalation-id>
D:\codex\factoryctl.cmd --session-token <token> reject <escalation-id>
D:\codex\factoryctl.cmd --session-token <token> session-close
```

## Natural interaction mapping

Interpret these user intents as controller actions:

- "查看状态" -> `daemon-status`, `control-layer-status`, `engineering-os-status`
- "查看实验室" -> `lab-status`
- "查看自治评分" -> `autonomy-score`
- "查看升级项" -> `escalations --open-only`
- "开始控制模式" -> `session-open`
- "结束控制模式" -> `session-close`
- "派发任务 ..." -> `dispatch`
- "批准 ..." -> `approve`
- "拒绝 ..." -> `reject`

## Dispatch rule

Every dispatch must specify:

- exact target workspace
- forbidden touch zones
- required artifact type
- validation requirement
- downgrade path
- return file path

For ToyOS, valid delivery must point back to `D:\codex\generated\toy-os-demo`.
Provider-only artifacts do not count as completed delivery.

## Constraints

- Do not modify runtime internals unless the task explicitly requires backend changes.
- Keep OpenCode-facing changes focused on wrappers, prompts, operator docs, and interaction flow.
- Treat the web UI as secondary.

For a minimal operator flow, the bridge script can be used directly:

```powershell
D:\codex\opencode-control.ps1 "查看状态"
D:\codex\opencode-control.ps1 "开始控制模式"
```
