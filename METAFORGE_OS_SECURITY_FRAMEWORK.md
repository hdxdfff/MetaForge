# MetaForge OS Security Framework

This document defines the production security architecture for MetaForge OS.

The goal is not "the model is always correct."
The goal is: if cognition drifts, the system still remains bounded, reviewable, and recoverable.

## Security Model

MetaForge OS security is split into four security planes:

```text
AI Security
|- Cognitive Security
|- Runtime Security
|- System Security
`- Evolution Security
```

This is the minimum stable model for a multi-agent local automation system that can plan, execute, patch, and improve itself.

## Design Principles

- control before autonomy
- state-backed enforcement instead of transcript-only promises
- bounded execution before trusted cognition
- explicit approval for high-risk or irreversible actions
- auditability for every meaningful state mutation

## 1. Cognitive Security

Purpose:

- prevent prompt-level manipulation
- prevent context poisoning
- prevent role hijacking
- prevent unsafe tool invocation requests from reaching the execution path unfiltered

### Threat classes

- prompt injection
- context poisoning
- tool manipulation
- role hijacking

### Control path

```text
User Input
   |
Prompt Firewall
   |
Context Sanitizer
   |
Policy Engine
   |
Model / Planner
```

### Prompt Firewall

The prompt firewall is the first cognitive boundary.

It should detect attempts to:

- override system or controller rules
- force hidden prompt disclosure
- coerce shell or tool execution
- impersonate operator, system, or reviewer roles

Current MetaForge-adjacent anchors:

- `D:\codex\orchestrator-mvp\tools\ai_guard.py`
- `D:\codex\orchestrator-mvp\data\guard_policy.json`

Target implementation path:

- `D:\codex\orchestrator-mvp\app\prompt_guard.py`

Required actions on match:

- `block` for explicit override or exfiltration attempts
- `sanitize` for suspicious but recoverable content
- `rewrite` for safe operator-visible restatement
- `audit` for all blocked or rewritten requests

### Context Sanitizer

The context sanitizer strips or downgrades hostile instructions before they become planning context.

It must remove or neutralize:

- malicious instruction carryover from prior turns
- tool override fragments
- fake authority markers
- hidden "ignore previous rules" chains

Current MetaForge-adjacent anchors:

- `D:\codex\orchestrator-mvp\tools\context_builder.py`
- `D:\codex\orchestrator-mvp\app\context_service.py`

Target implementation path:

- `D:\codex\orchestrator-mvp\app\context_sanitizer.py`

### Cognitive policy contract

The planner may reason over user intent.
It may not directly reinterpret:

- role privileges
- workspace lock
- approval requirements
- hidden system policy

Those are control-plane facts, not model opinions.

## 2. Runtime Security

Purpose:

- preserve safety even when a model produces a bad plan
- prevent dangerous tool execution
- keep execution bounded by role, workspace, and resource policy

This is the most important MetaForge security layer.

### Runtime modules

```text
Runtime Security
|- Tool Permission
|- Sandbox
|- Execution Guard
`- Resource Guard
```

### Tool Permission System

Every agent or lane must execute under explicit tool permissions.

Permission model:

```text
Agent
  |
Role
  |
Tool Policy
```

Current MetaForge anchors:

- `D:\codex\orchestrator-mvp\tools\privilege_policy.py`
- `D:\codex\orchestrator-mvp\tools\session_guard.py`
- `D:\codex\orchestrator-mvp\data\approval_policy.json`
- `D:\codex\orchestrator-mvp\data\session_policy.json`

Recommended hardening:

- split command approval from tool availability
- make permissions role-scoped and workspace-scoped
- require explicit deny rules for destructive actions
- attach policy decisions to every execution trace record

Target implementation path:

- `D:\codex\orchestrator-mvp\data\tool_policy.json`

Minimum role examples:

- `research_agent`: web search, repo read, no shell write
- `worker_agent`: bounded file write, no dependency install by default
- `safety_agent`: read logs, inspect policy, veto high-risk execution
- `audit_agent`: append-only log write, no code mutation

### Execution Guard

Execution guard blocks or escalates dangerous commands even if the planner emits them.

It must inspect:

- shell commands
- patch intents
- filesystem deletion
- package installation
- network-capable execution

Hard block examples:

- recursive deletion outside approved workspace
- system shutdown or service kill without approval
- credential exfiltration or secret dump commands
- unapproved remote execution patterns

Escalation examples:

- dependency install
- docker runtime changes
- write access outside bounded workspace
- controller or agent mutation

Current MetaForge anchors:

- `D:\codex\orchestrator-mvp\tools\privilege_policy.py`
- `D:\codex\METAFORGE_OS_WORKSPACE_LOCK_ENFORCEMENT_PROPOSAL.md`
- `D:\codex\METAFORGE_OS_TOYOS_ROUTING_GUARD_PATCH_PROPOSAL.md`

Target implementation path:

- `D:\codex\orchestrator-mvp\app\execution_guard.py`

### Sandbox

All nontrivial execution should run inside a bounded execution environment.

Acceptable isolation patterns:

- Docker
- Firecracker-style VM
- worker VM templates
- restricted Python runners

Current MetaForge anchors:

- `D:\codex\orchestrator-mvp\tools\vm_orchestrator.py`
- `D:\codex\orchestrator-mvp\tools\sandbox_upgrade_runner.py`
- `D:\codex\orchestrator-mvp\data\worker_vm_policy.json`
- `D:\codex\orchestrator-mvp\data\vm_templates.json`

Target implementation path:

- `D:\codex\orchestrator-mvp\app\sandbox_executor.py`

### Resource Guard

The system must limit overconsumption caused by loops, bad planning, or adversarial inputs.

Protected resources:

- CPU
- memory
- disk
- network
- strong-model quota
- task creation rate

Current MetaForge anchors:

- `D:\codex\orchestrator-mvp\tools\ai_guard.py`
- `D:\codex\orchestrator-mvp\app\budget_manager.py`
- `D:\codex\orchestrator-mvp\data\guard_policy.json`

Resource guard decisions must be able to:

- throttle
- pause
- degrade to report/proposal mode
- block high-cost loops

## 3. System Security

Purpose:

- secure the broader software system around the model
- protect code mutation paths, dependency intake, secrets, and audit evidence

### System modules

```text
System Security
|- Patch Gate
|- Dependency Guard
|- Secret Manager
`- Audit Log
```

### Patch Gate

MetaForge already has the start of this.

Required flow:

```text
proposal
  ->
review
  ->
test
  ->
deploy
```

Current anchors:

- `D:\codex\orchestrator-mvp\tools\approve_self_patch.py`
- `D:\codex\orchestrator-mvp\tools\self_patch_loop.py`
- `D:\codex\orchestrator-mvp\data\approved_patch_policy.json`
- `D:\codex\orchestrator-mvp\data\approved_patch_records.json`
- `D:\codex\orchestrator-mvp\data\patch_submissions.json`

Patch gate rule:

- no silent self-modification of the controller, policy layer, or safety layer

### Dependency Guard

Dependency installation is a high-risk action.

It must enforce:

- package allowlist
- source trust policy
- install intent logging
- manual review for non-allowlisted installs

Current anchor:

- `D:\codex\orchestrator-mvp\tools\privilege_policy.py`

Expansion target:

- `D:\codex\orchestrator-mvp\data\dependency_policy.json`

### Secret Manager

Secrets must be isolated from planner and worker context whenever possible.

Protected data classes:

- API keys
- tokens
- passwords
- cookies
- signing secrets

Required policy:

- never persist secrets into task memory or audit summaries
- never expose secret values to low-trust worker lanes
- pass handles or references instead of raw values where possible

Current anchors:

- `D:\codex\orchestrator-mvp\.env`
- `D:\codex\orchestrator-mvp\app\config.py`

Longer-term target:

- external vault-backed resolution

### Audit Log

MetaForge must stay explainable after the fact.

Every important action should be reconstructable from durable records.

Minimum audit subjects:

- agent identity
- decision source
- tool call
- file mutation
- approval decision
- self-improvement action
- deployment or promotion action

Current anchors:

- `D:\codex\orchestrator-mvp\data\audit_log.json`
- `D:\codex\orchestrator-mvp\data\execution_trace.jsonl`
- `D:\codex\orchestrator-mvp\data\decision_log.json`
- `D:\codex\orchestrator-mvp\tools\execution_trace.py`

Audit rule:

- safety-relevant events must be append-only and timestamped

## 4. Evolution Security

Purpose:

- keep self-improvement bounded
- prevent uncontrolled architecture drift
- require validation before adoption

This becomes critical once MetaForge starts modifying its own execution and control paths.

### Self-Improvement Pipeline

```text
idea
  ->
proposal
  ->
simulation
  ->
review
  ->
deploy
```

Current anchors:

- `D:\codex\METAFORGE_OS_SELF_IMPROVEMENT_LOOP.md`
- `D:\codex\orchestrator-mvp\tools\evolution_control.py`
- `D:\codex\orchestrator-mvp\tools\experiment_executor.py`
- `D:\codex\orchestrator-mvp\data\evolution_control.json`
- `D:\codex\orchestrator-mvp\data\evolution_history.json`

Mandatory rules:

- self-upgrade cannot bypass patch gate
- self-upgrade cannot widen privileges without review
- self-upgrade cannot redefine KPI success on its own
- self-upgrade must preserve rollback path

### Simulation Layer

All upgrade candidates should first run in:

- a shadow system
- a test cluster
- a sandbox lane
- a replay harness against historical tasks

Existing MetaForge-adjacent anchors:

- `D:\codex\orchestrator-mvp\tools\experiment_planner.py`
- `D:\codex\orchestrator-mvp\tools\experiment_evaluator.py`
- `D:\codex\orchestrator-mvp\data\experiment_history.json`

## 5. Organizational Safety

When MetaForge behaves like an AI organization, safety must also be role-distributed.

Recommended role set:

- `worker_agent`: executes bounded tasks
- `supervisor_agent`: reviews quality and output validity
- `safety_agent`: evaluates risk and vetoes unsafe execution
- `audit_agent`: preserves durable evidence

This should be reflected in both runtime permissions and task routing.

Target implementation path:

- `D:\codex\orchestrator-mvp\app\safety_agent.py`

## MetaForge Security Architecture

```text
                 Governance Layer
                        |
                  Policy Engine
                        |
        +---------------+---------------+
        |               |               |
 Prompt Firewall   Tool Guard     Upgrade Guard
        |               |               |
        +------ Runtime Security Monitor ------+
                        |
                    AI Agents
                        |
                   Sandbox Layer
                        |
                    System Kernel
```

### Mapping to current MetaForge OS

- Governance Layer: CEO agent, control layer, approval policy, KPI policy
- Policy Engine: `global_policy_engine.py`, `privilege_policy.py`, session policy
- Prompt Firewall: new bounded entry filter before planning and tool binding
- Tool Guard: approval policy, workspace lock, session guard, privilege policy
- Upgrade Guard: self-patch approval, evolution control, patch records
- Runtime Security Monitor: `ai_guard.py`, health status, core message escalation
- Sandbox Layer: VM orchestrator, sandbox upgrade runner, worker VM policy

## Current Priority Modules

For the current MetaForge stage, these are the highest-value missing or incomplete modules:

1. `D:\codex\orchestrator-mvp\app\prompt_guard.py`
2. `D:\codex\orchestrator-mvp\data\tool_policy.json`
3. `D:\codex\orchestrator-mvp\app\safety_agent.py`
4. `D:\codex\orchestrator-mvp\app\sandbox_executor.py`
5. strengthen append-only guarantees around `D:\codex\orchestrator-mvp\data\audit_log.json`

## Implementation Order

1. Put prompt filtering and context sanitization in front of planning.
2. Normalize tool permissions into one role-scoped policy surface.
3. Add execution guard checks before shell, patch, install, and delete actions.
4. Route risky execution through a sandbox executor instead of direct adapters.
5. Treat audit evidence as a first-class state product, not debug output.
6. Require simulation plus patch gate for any self-upgrade touching controller or policy code.

## Security Acceptance Criteria

MetaForge security is considered minimally credible only if:

- prompt override attempts are blocked or sanitized before planner execution
- high-risk tools require explicit policy approval
- workspace lock cannot be bypassed by capability routing
- dangerous execution is blocked even when the model requests it
- self-upgrade cannot skip simulation and review
- every safety-relevant decision is recoverable from audit state

## Final Rule

The terminal security equation for MetaForge OS is:

```text
AI Safety = Control + Transparency + Limited Autonomy + Auditability
```

MetaForge may act.
It must always remain governable.
