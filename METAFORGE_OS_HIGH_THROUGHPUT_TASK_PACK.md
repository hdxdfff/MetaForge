# MetaForge OS High-Throughput Task Pack

This package is the first executable batch for:

- `D:\codex\METAFORGE_OS_HIGH_THROUGHPUT_BLUEPRINT.md`
- `D:\codex\orchestrator-mvp\contracts\schemas\task.schema.json`

## Use

Dispatch the JSON tasks in this order:

1. research lane audit
2. research lane schema delta
3. chore lane rollout checklist
4. ToyOS smoke and regression pack

Example batch command:

```powershell
D:\codex\tools\python311-embed\python.exe D:\codex\orchestrator-mvp\tools\dispatch_task.py --task-file D:\codex\METAFORGE_OS_HIGH_THROUGHPUT_TASK_PACK.json --continue-on-error
```

## Package rules

- Each task already carries a queue name, verification level, runtime cap, retry limit, and rollback rule.
- The controller should reject the task if queue capacity or WIP limits are exceeded.
- The ToyOS task must land in `D:\codex\generated\toy-os-demo`.

## Expected outputs

- bounded implementation note or patch plan
- dispatch schema delta
- rollout checklist delta
- ToyOS smoke/regression bundle proposal or execution plan
