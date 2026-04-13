# AI Runtime Diagnostic

Generated: 2026-03-13 Asia/Shanghai

## 1. Model Router Status

- Router state file: `D:\codex\orchestrator-mvp\data\provider_gateway_state.json`
- `openai-planner` is unhealthy on all tracked candidates.
- `cheap` lane is also unhealthy on all tracked candidates.
- Both tracked routes point to `http://localhost:11434` and are currently in circuit-open state.
- Current task payloads still carry planner metadata such as `planner_model: gpt-5.4-pro`, but runtime evidence shows the planner lane is not successfully servicing requests.

## 2. Provider Auth Status

- Current primary evidence does **not** show a live authentication failure.
- Current primary failures are:
  - `APIConnectionError: Connection error.`
  - `ImportError: Using SOCKS proxy, but the 'socksio' package is not installed.`
- AI test lane is also degraded with `NameError`, which means some test failures are internal/runtime failures rather than provider-auth failures.
- Conclusion: today's blocker is broader than auth. The live failures are connection/runtime-path failures, so even the cheap lane is not healthy.

## 3. LLM Calls Today

- Usage file: `D:\codex\orchestrator-mvp\data\usage_tracker.json`
- `today_call_count = 0`
- `usage_tracker.json` last updated at `2026-03-12T11:33:36Z`, not today.
- `cheap_calls = 26`, `strong_calls = 0`, but those are from the last recorded 24h window ending yesterday.
- Conclusion: there is no recorded LLM call usage for 2026-03-13 in the current usage tracker.

## 4. Tokens Per Model

- No trustworthy per-model token ledger exists for today in the inspected runtime files.
- `usage_tracker.json` records call counts and last model, but not token totals.
- `llm_checkpoints.json` records provider/model/status/prompt chars, but no current-day token totals and no recent 2026-03-13 successful LLM events.
- Best available evidence:
  - last recorded model usage: `cheap / deepseek-chat`
  - strong-model recorded usage: `0`
- Conclusion: the system currently has an **observability gap** for `tokens per model today`.

## 5. Planner Runs

- Planner evidence files:
  - `D:\codex\orchestrator-mvp\data\brain_loop_state.json`
  - `D:\codex\orchestrator-mvp\data\experiment_plan.json`
- Latest brain-loop snapshot shows:
  - `planner_compile_runs = 2`
  - `scheduling_kernel_runs = 1`
  - `dispatch_count = 1`
- Experiment planner is alive:
  - `candidate_count = 5`
  - selected experiment: `Experiment coder prompt specialization`
- Conclusion: planning exists and is running, but planner execution is not translating into recorded model usage today.

## 6. Evaluator Runs

- Evaluator evidence files:
  - `D:\codex\orchestrator-mvp\data\experiment_run.json`
  - `D:\codex\orchestrator-mvp\data\experiment_evaluation.json`
  - `D:\codex\orchestrator-mvp\data\ai_runtime_state.json`
- Latest experiment run:
  - `status = completed`
- Latest experiment evaluation:
  - `status = evaluated`
  - `adopt = true`
  - `score = 0.9185`
- Reasoning stream also contains evaluator activity:
  - `decision = run evaluator_loop.py`
- Conclusion: evaluator path exists and has executed, but it is not proving live provider-backed LLM traffic today.

## 7. Reasoning Nodes

- Reasoning evidence file: `D:\codex\orchestrator-mvp\data\ai_runtime_state.json`
- `reasoning.count = 20`
- Sources present in reasoning stream:
  - `self_model`
  - `generator`
  - `self-improvement`
  - `evaluation`
  - `telemetry`
  - `meta-factory`
  - `sandbox`
  - `adoption`
- Important detail:
  - reasoning rows exist,
  - but they are mostly control-plane decisions and maintenance actions,
  - not proof of successful external LLM completions today.

## 8. Task vs LLM Ratio

- Task evidence:
  - `D:\codex\orchestrator-mvp\data\ai_runtime_state.json`
  - `D:\codex\orchestrator-mvp\data\tasks.json`
- Current runtime snapshot:
  - `tasks.count = 119`
  - `tasks.active_count = 119`
  - `task_rows_today = 36` in `ai_runtime_state.json`
- LLM usage evidence today:
  - `recorded_llm_calls_today = 0`
- Effective ratio from current telemetry:
  - `36+ task updates : 0 recorded LLM calls today`
- Conclusion: this is a classic `busy control plane, low recorded inference throughput` pattern.

## Overall Diagnosis

The system is not simply idle. It is producing tasks, planning goals, dispatching nodes, and running evaluator/maintenance loops. The main issue is that the live model routes are unhealthy, while usage telemetry shows no recorded LLM calls today.

Most likely causes, in order:

1. Provider gateway is failing before planner/cheap lanes can complete requests.
2. Reasoning is happening mostly in controller/self-model/control-loop space rather than provider-backed completions.
3. Usage tracking for today is stale, so even if some calls occurred, current token observability is incomplete.
4. AI test lane is degraded, which likely reinforces conservative routing and suppresses premium escalation.

## Immediate Operator Read

- `model router status`: unhealthy
- `provider auth status`: no live auth proof today; current failures are connection/import/runtime
- `llm calls today`: 0 recorded
- `tokens per model`: not observable with current telemetry
- `planner runs`: yes
- `evaluator runs`: yes
- `reasoning nodes`: yes
- `task vs llm ratio`: heavily skewed toward tasks/control flow

## Files Used

- `D:\codex\orchestrator-mvp\data\provider_gateway_state.json`
- `D:\codex\orchestrator-mvp\data\usage_tracker.json`
- `D:\codex\orchestrator-mvp\data\llm_checkpoints.json`
- `D:\codex\orchestrator-mvp\data\ai_test_status.json`
- `D:\codex\orchestrator-mvp\data\brain_loop_state.json`
- `D:\codex\orchestrator-mvp\data\experiment_plan.json`
- `D:\codex\orchestrator-mvp\data\experiment_run.json`
- `D:\codex\orchestrator-mvp\data\experiment_evaluation.json`
- `D:\codex\orchestrator-mvp\data\ai_runtime_state.json`
- `D:\codex\orchestrator-mvp\data\tasks.json`
