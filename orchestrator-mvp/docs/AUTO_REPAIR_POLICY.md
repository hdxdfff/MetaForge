# Auto Repair Policy

This policy keeps repair activity safe and auditable.

Allowed automatically when policy permits:

- `rebuild_priority_tasks`
- `poke_scheduler`
- `switch_provider_fallback`
- `re_run_verification`
- `freeze_release_train`

Conditioned actions:

- `soft_restart_dispatcher`

Rules:

- critical risks require human review
- system-wide destructive operations are forbidden
- repairs must preserve evidence
- repeated repair loops should cool down before retry
- release promotion can be frozen, but runtime should keep flowing

