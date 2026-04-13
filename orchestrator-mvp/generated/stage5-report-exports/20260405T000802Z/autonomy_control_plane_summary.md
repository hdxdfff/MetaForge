# Autonomy Control Plane Summary

- status: pass
- updated_at: 2026-04-04T23:08:02.972500Z
- autonomy_stage: stage3
- control_status: attention
- release_status: pass
- industrial_operations_status: normal
- industrial_readiness_status: attention
- closed_pools: P2
- sandbox_p2_allowed: False

## P2 Sandbox

- status: blocked
- lane: p2_low_risk
- allow_p2_sandbox: False
- budget_pool: P2
- budget_gate: sandbox_closed
- admission_lane: sandbox_low_risk
- task_classes: doc_patch, report_refresh, json_fix, manifest_patch, config_fix, unit_test_run, build_fix, artifact_audit
- operator_action: can edit this field set in the control plane summary while P2 remains sandbox-only

## Auto-Executable

- AUTO: status_check, report_refresh, dashboard_refresh

## Requires Approval

- release: deploy_production, release_candidate, git_push, modify_controller, modify_agents, filesystem.delete, filesystem.write_core
- core_mutation: modify_agents, modify_controller, filesystem.write_core, filesystem.delete
- external_change: install_package, docker.run, cross_repo_change

## Budget / Pools

- open_pools: P0, P1, P3
- closed_pools: P2
- daily_budgets: {"self_repair_daily": 5, "artifact_growth_daily": 2, "capability_expansion_daily": 1, "sandbox_p2_daily": 1, "research_daily": 1}
- usage_24h: {"self_repair_daily": {"limit": 5, "used_24h": 3, "remaining_24h": 2, "headroom_ratio": 0.4, "burn_rate": 0.6, "window_basis": "rolling_24h_ledger", "next_replenishment_at": null, "source": "self_repair_ledger"}, "artifact_growth_daily": {"limit": 2, "used_24h": 0, "remaining_24h": 2, "headroom_ratio": 1.0, "burn_rate": 0.0, "window_basis": "rolling_24h", "next_replenishment_at": null}, "capability_expansion_daily": {"limit": 1, "used_24h": 9, "remaining_24h": 0, "headroom_ratio": 0.0, "burn_rate": 9.0, "window_basis": "rolling_24h_ledger", "next_replenishment_at": "2026-04-03T19:17:38.418652Z", "source": "capability_expansion_ledger"}, "sandbox_p2_daily": {"limit": 1, "used_24h": 4, "remaining_24h": 0, "headroom_ratio": 0.0, "burn_rate": 4.0, "window_basis": "rolling_24h", "next_replenishment_at": "2026-04-04T19:03:58.835314Z"}, "research_daily": {"limit": 1, "used_24h": 0, "remaining_24h": 1, "headroom_ratio": 1.0, "burn_rate": 0.0, "window_basis": "rolling_24h", "next_replenishment_at": null}}

## Recovery / Fuse

- auto_recovery_success_rate: 0.9941
- mttr_minutes: 0.0
- failed_release_rollback_time_minutes: 0.0
- freeze_triggered: False
- release_gate_signal_count: 1

## Operator Controls

- editable: industrial_operations.budget_control.gates.allow_p2
- editable: industrial_operations.budget_control.gates.allow_p2_sandbox
- editable: industrial_operations.budget_control.gates.allow_p3
- editable: industrial_operations.budget_control.policy
- editable: control_policy.approvals
- editable: tool_policy.roles
- editable: session_policy.roles
- approval_required: modify_controller
- approval_required: modify_agents
- approval_required: deploy_production
- approval_required: filesystem.write_core
- approval_required: filesystem.delete
- approval_required: git.push
- approval_required: install_package
- approval_required: docker.run

## Policy Files

- control_policy_path: D:\codex\orchestrator-mvp\data\control_policy.json
- approval_policy_path: D:\codex\orchestrator-mvp\data\approval_policy.json
- session_policy_path: D:\codex\orchestrator-mvp\data\session_policy.json
- tool_policy_path: D:\codex\orchestrator-mvp\data\tool_policy.json
