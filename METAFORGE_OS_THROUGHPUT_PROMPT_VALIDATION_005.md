# Throughput Prompt Validation 005

## target_files

1. [D:\codex\orchestrator-mvp\app\audit_validation.py](D:\codex\orchestrator-mvp\app\audit_validation.py)
2. [D:\codex\orchestrator-mvp\app\worker_adapters.py](D:\codex\orchestrator-mvp\app\worker_adapters.py)
3. [D:\codex\orchestrator-mvp\app\orchestrator.py](D:\codex\orchestrator-mvp\app\orchestrator.py)
4. [D:\codex\orchestrator-mvp\app\models.py](D:\codex\orchestrator-mvp\app\models.py)
5. [D:\codex\orchestrator-mvp\tests\test_worker_adapters_schema_validation.py](D:\codex\orchestrator-mvp\tests\test_worker_adapters_schema_validation.py)

## smallest_gap

The audit completion path is now parsed as structured output rather than keyword matching. The remaining scope gap is bounded: the new guard applies to `artifact_audit` task outputs in both research and production contexts, but only for coder/reviewer steps, not planner steps.

## patch_plan

1. Introduce canonical audit output models for coder and reviewer steps.
2. Parse audit outputs from markdown sections or structured JSON-like payloads.
3. Reject coder/reviewer completion when required sections are missing or malformed.
4. Keep planner steps exempt so task understanding can remain free-form.

## validation_commands

```powershell
D:\codex\tools\python311-embed\python.exe -m py_compile D:\codex\orchestrator-mvp\app\audit_validation.py D:\codex\orchestrator-mvp\app\worker_adapters.py D:\codex\orchestrator-mvp\app\orchestrator.py D:\codex\orchestrator-mvp\app\models.py D:\codex\orchestrator-mvp\tests\test_worker_adapters_schema_validation.py
python D:\codex\orchestrator-mvp\tests\test_worker_adapters_schema_validation.py
```

## residual_risk

- The parser is intentionally strict; malformed free-form audit responses will be rejected rather than repaired.
- Non-audit task types are not affected by this guard.

## bounded_next_step

Use the same structured audit contract for any future `artifact_audit` packs so the completion gate stays deterministic and reviewable.

