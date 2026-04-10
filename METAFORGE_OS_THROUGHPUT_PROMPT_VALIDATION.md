# Throughput Prompt Validation

## target_files

1. [D:\codex\orchestrator-mvp\app\orchestrator.py](D:\codex\orchestrator-mvp\app\orchestrator.py)
2. [D:\codex\orchestrator-mvp\app\worker_adapters.py](D:\codex\orchestrator-mvp\app\worker_adapters.py)
3. [D:\codex\METAFORGE_OS_THROUGHPUT_PROMPT_VALIDATION.md](D:\codex\METAFORGE_OS_THROUGHPUT_PROMPT_VALIDATION.md)

## smallest_gap

The research/governance audit path was still too loose before this change. The model could return generic summaries because the worker prompts did not carry an explicit structured output contract, and the orchestrator prompt only described the task at a high level.

## patch_plan

1. Add an explicit output contract in `orchestrator.py` for research/governance audit tasks.
2. Inject structured worker instructions in `worker_adapters.py` so coder and reviewer prompts require concrete files, gaps, validation commands, and residual risk.
3. Re-dispatch a validation task and verify the returned artifact is concrete instead of generic.

## validation_commands

```powershell
D:\codex\tools\python311-embed\python.exe -m py_compile D:\codex\orchestrator-mvp\app\orchestrator.py D:\codex\orchestrator-mvp\app\worker_adapters.py
D:\codex\factoryctl.cmd control-layer-status
D:\codex\tools\python311-embed\python.exe D:\codex\orchestrator-mvp\tools\dispatch_task.py --task-file D:\codex\METAFORGE_OS_THROUGHPUT_PROMPT_VALIDATION_PACK.json --continue-on-error --timeout 300
```

## residual_risk

- Structural prompt enforcement is now explicit, but content quality still depends on the model following the contract.
- The current guard is strongest for `artifact_audit`, `json_fix`, `report_refresh`, `doc_patch`, and `manifest_patch` tasks; other task types still use the broader contract.

## bounded_next_step

Use the validation task output as the accepted baseline for future research/governance audit work, and promote the same structured prompt contract into any additional audit task packs.
