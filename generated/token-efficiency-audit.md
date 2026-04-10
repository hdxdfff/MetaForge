# Token Efficiency Audit

Date: 2026-03-15
Workspace: D:\codex\orchestrator-mvp

## Goal
Reduce unnecessary token spend and improve useful output per request in the orchestrator control plane.

## Baseline Findings
- Planner, coder, and reviewer traffic was biased toward the reasoning lane more often than needed.
- Planner prompts were verbose and duplicated schema text in the remote chat branch.
- Usage telemetry tracked provider mix but not prompt/output efficiency.
- Autonomy scoring could switch to a 1 hour window with only 1 call, which overstated reasoning ratio and distorted lane-mix interpretation.

## Changes Applied
- Route default coder and reviewer work to the cheap lane; reserve reasoning for architectural or high-risk steps.
- Prefer the cheap planner first for small, non-strategic tasks.
- Compress planner and dispatch prompts to reduce prompt overhead.
- Record input/output character totals and output-input ratio in LLM usage telemetry.
- Update usage and autonomy scoring to use non-fallback ratio plus output-input ratio.
- Require a minimum sample size before autonomy score trusts the 1 hour recent window.
- Remove duplicated JSON schema text from the remote planner chat branch.
- Add a bounded artifact-generation fallback plan so document-only tasks do not default to `pytest` shell validation.
- Restart the local API so live telemetry uses the updated code.

## Files Changed
- D:\codex\orchestrator-mvp\app\model_router.py
- D:\codex\orchestrator-mvp\app\openai_client.py
- D:\codex\orchestrator-mvp\app\orchestrator.py
- D:\codex\orchestrator-mvp\app\llm_service.py
- D:\codex\orchestrator-mvp\tools\usage_tracker.py
- D:\codex\orchestrator-mvp\tools\autonomy_score.py

## Live Validation Findings
- Task id `9fbd25bf11e14b3893837dadafc47032` proved that the old fallback plan inserted `pytest` for an artifact-only request and paused on WSL failure.
- After the API restart, a direct `LlmService.generate()` probe wrote real telemetry with `input_chars=121`, `output_chars=93`, and `used_fallback=false`.
- New recent events now include both cheap and reasoning records with character counts, so output-input ratio is measured rather than a fallback placeholder.

## Current Metrics
- usage_tracker full-window calls: cheap=62, reasoning=22, strong=0, total=84
- usage_tracker recent-window calls: cheap=6, reasoning=1, strong=0, total=7
- usage_tracker effective ratio source: recent_window
- usage_tracker reasoning ratio: 0.2619 full-window, 0.1429 recent-window effective
- usage_tracker total input chars: 942
- usage_tracker total output chars: 1257
- usage_tracker output-input ratio: 1.3344
- autonomy_score: 0.765
- autonomy lane_mix source: recent_window
- control-layer status: operator_attention
- quality score: 0.8571
- quality status: promote
- daemon status: running

## Validation
- `python -m compileall app tools`
- `python tools\usage_tracker.py`
- `python tools\autonomy_score.py`
- `powershell -ExecutionPolicy Bypass -File D:\codex\factoryctl.ps1 control-layer-status`
- `powershell -ExecutionPolicy Bypass -File D:\codex\factoryctl.ps1 autonomy-score`
- `powershell -ExecutionPolicy Bypass -File D:\codex\factoryctl.ps1 daemon-status`
- Live dispatch sample through `POST /api/dispatch`
- `python -m compileall app` after the artifact-only fallback fix
- Direct runtime probe through `app.llm_service.LlmService.generate()`

## Residual Risk
- The direct LLM probe validated telemetry writing, but it did not prove end-to-end task persistence after the API restart; the restarted API returned an empty `/api/tasks` list and a follow-up dispatch could not be polled reliably.
- The sample task `9fbd25bf11e14b3893837dadafc47032` remains paused in `waiting_approval` after the old fallback plan attempted `pytest`.
- `autonomy_score` now reacts to real recent-window samples, so its score can drop when the last 1 hour mix is cheap-heavy or below the target reasoning band.
- `control-layer-status` metadata previously reported `kernel_mode.model_router.default_lane=reasoning`; if operators depend on that field, controller metadata should be reconciled with runtime routing rules.

## Recommended Next Step
Inspect why the restarted API is not repopulating `/api/tasks`, then rerun one bounded artifact task through the task API to confirm that the new artifact-only fallback avoids shell validation end-to-end.
