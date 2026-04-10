# MetaForge OS High-Throughput Blueprint

This blueprint operationalizes:

- `D:\codex\METAFORGE_OS_KPI_POLICY.md`
- `D:\codex\METAFORGE_OS_SATURATION_POLICY.md`
- `D:\codex\METAFORGE_OS_DISPATCH_TEMPLATE.md`
- `D:\codex\METAFORGE_OS_CHORE_QUEUE_POLICY.md`

It turns throughput into an execution contract instead of a slogan.

## 1. Throughput definition

High throughput means four measurable outcomes:

1. Task throughput
   - completed verified tasks per hour
   - completed verified tasks per 24h
   - completed tasks by type: `build_fix`, `test_add`, `harness_run`, `report_refresh`, `artifact_audit`, `doc_patch`, `demo_rebuild`, `path_repair`
2. First-result speed
   - `dispatch -> first result` median
   - `dispatch -> final verdict` median
3. Verification success
   - task pass rate
   - first-pass acceptance rate
   - retry rate
   - rollback rate
4. Real artifact conversion
   - task -> artifact conversion rate
   - artifact -> real artifact conversion rate
   - new real artifacts per 24h

## 2. Non-negotiable task schema

Every queueable task must include these fields before dispatch:

```json
{
  "task_id": "task_20260329_001",
  "task_type": "harness_case_add",
  "priority": "fastlane",
  "project": "ToyOS",
  "artifact_spec": "toyos_harness_regression",
  "input": {
    "target_file": "kernel/syscall_write.c",
    "goal": "add one atomic regression case"
  },
  "expected_output": {
    "files": [
      "harness_runs/run_xxx/evaluation_report.json"
    ],
    "state_change": "harness_regression_status updated"
  },
  "verification_level": "L2",
  "max_runtime_seconds": 1800,
  "retry_limit": 1,
  "rollback_rule": "mark_failed_and_requeue_split",
  "ownership": {
    "planner": "dispatcher",
    "executor": "harness_worker",
    "verifier": "independent_evaluator"
  }
}
```

Rules:

- `task_type` must be one of the approved types.
- `artifact_spec` must name the concrete artifact or registry entry.
- `verification_level` must be set before execution.
- `max_runtime_seconds` must be bounded.
- tasks missing these fields do not enter the main production queues.

## 3. Queue architecture

Use four queues, each with a distinct purpose and WIP cap.

### 3.1 Fastlane

Purpose:

- low-risk, short, atomic work

Typical tasks:

- doc patch
- JSON repair
- report refresh
- small config fix
- harness case addition
- manifest completion

SLA target:

- start within 5 minutes
- first result within 15 minutes
- final verdict within 30 minutes

### 3.2 Build/Test

Purpose:

- build, unit test, smoke, packaging, demo rebuild

Typical tasks:

- `build_fix`
- `unit_test_run`
- `demo_rebuild`
- `package_validation`

Queue rule:

- do not allow build/test work to block fastlane

### 3.3 Regression/Harness

Purpose:

- run regressions and independent evaluators

Typical tasks:

- `harness_regression_run`
- `qemu_smoke_run`
- `atomic_feature_validation`
- `independent_evidence_check`

Queue rule:

- keep this queue isolated from ordinary production tasks
- it exists to protect verification throughput

### 3.4 Incubation

Purpose:

- new product bootstrap
- subsystem refactor
- architecture migration
- heavy exploratory work

Queue rule:

- strict rate limit
- never let incubation consume the resources reserved for evidence refresh or regression

## 4. Worker specialization

Do not let every worker do every job.

### 4.1 `builder_worker`

Owns:

- build
- compile repair
- dependency repair
- packaging

Outputs:

- build reports
- artifact files

### 4.2 `tester_worker`

Owns:

- unit tests
- smoke tests
- execution summaries

Outputs:

- test reports
- execution reports

### 4.3 `harness_worker`

Owns:

- atomic harness cases
- evidence collection
- harness status updates

Outputs:

- run directory
- evaluation report
- metric updates

### 4.4 `audit_worker`

Owns:

- artifact manifest checks
- evidence completeness checks
- registry reconciliation
- freshness and consistency checks

Outputs:

- audit verdict

### 4.5 `doc_worker`

Owns:

- status reports
- milestone reports
- handoff documents
- operator-facing summaries

Outputs:

- report artifacts

### 4.6 `incubator_worker`

Owns:

- new product experiments
- long-horizon prototypes
- design decomposition

Rule:

- keep this pool small

## 5. WIP limits

Throughput collapses when the same object is touched by too many tasks.

Apply three layers of WIP control:

1. Per queue
   - example cap: `fastlane=6`, `build_test=3`, `regression=2`, `incubation=1`
2. Per project
   - example cap: ToyOS max 4 concurrent tasks
3. Per artifact
   - example cap: one rebuild plus one audit at a time for the same artifact

If a task would violate a WIP cap, it must wait or be split.

## 6. Verification ladder

Verification cost must match task value.

### L1: Light verification

Use for fastlane.

Checks:

- file exists
- JSON parses
- required fields present
- command exit code
- timestamp freshness

Target duration:

- 10 seconds to 1 minute

### L2: Standard verification

Use for build/test work.

Checks:

- build pass
- test pass
- evidence generated
- manifest validity
- registry reconciliation

Target duration:

- 1 to 10 minutes

### L3: Heavy verification

Use only for release candidates or real-artifact candidates.

Checks:

- QEMU smoke
- harness regression
- independent evaluator
- multi-evidence consistency
- artifact audit pass

Target duration:

- 5 to 30 minutes

Rule:

- most tasks should stop at L1 or L2
- L3 is reserved for promotion, milestone reports, and release candidates

## 7. Dispatch scoring

Schedule for flow, not for symbolism.

Prefer tasks with:

- shorter runtime
- lower risk
- clearer artifact dependency
- older queue age

Penalize tasks with:

- heavy validation
- lock contention
- wide blast radius

Suggested score:

```text
dispatch_score =
  short_runtime_bonus
+ low_risk_bonus
+ artifact_dependency_bonus
+ queue_wait_bonus
- heavy_validation_penalty
- lock_conflict_penalty
```

Dispatch rule:

- if two tasks are otherwise equal, choose the one that can return the first verified artifact sooner

## 8. Failure handling

Treat failures as routing signals, not as terminal drama.

### 8.1 Auto-retry

Retry once or twice when the failure is transient.

Examples:

- network loss
- provider error
- brief file lock conflict

### 8.2 Degrade

Reduce validation cost when the strong path is unavailable.

Examples:

- downgrade from L3 to L2
- move from strong lane to cheap lane

### 8.3 Split and requeue

Split oversized tasks into atomic work units.

Examples:

- patch too large
- regression bundle too broad
- context budget exceeded

### 8.4 Fail fast

Stop immediately when the task contract is invalid.

Examples:

- wrong path
- missing artifact spec
- incomplete verification contract
- permission violation

## 9. Control metrics

Track only the indicators that actually steer the system:

1. `completed_tasks_last_24h`
2. `first_result_median_minutes`
3. `final_verdict_median_minutes`
4. `queue_wait_median_minutes`
5. `pass_rate_by_task_type`
6. `retry_rate`
7. `real_artifact_conversion_rate`
8. `flakiness_by_harness_case`

Operational rule:

- if a metric cannot drive a routing or capacity decision, it does not belong on the main dashboard

## 10. Rollout sequence

Do this in order.

### Phase 1: Industrialize evidence refresh

Goal:

- stabilize report refresh, demo rebuild, harness runs, and audits

Deliverables:

- fixed task schema
- queue split
- L1/L2/L3 verification rules
- dashboard for the 8 core metrics

Success criteria:

- higher 24h verified task count
- lower first-result time
- stable evidence completeness
- lower retry rate

### Phase 2: Convert verification throughput into artifact throughput

Goal:

- turn recurring verification work into incremental product capability

Deliverables:

- small, steady artifact additions
- repeatable regression bundles
- stable registry growth

Success criteria:

- real artifact count increases over time
- registry growth is matched by verification

### Phase 3: Multi-product parallelization

Goal:

- separate product lines into independent pools
- avoid cross-contamination of queues and evidence

Deliverables:

- per-product worker pools
- release train automation
- fairness rules across projects

Success criteria:

- one product line cannot starve another
- release work no longer blocks evidence work

## 11. Minimum viable implementation set

If the system cannot absorb the full blueprint at once, implement only these six items first:

1. Enforce task schema admission
2. Split into four queues
3. Split workers by capability
4. Add L1/L2/L3 verification
5. Apply WIP caps
6. Publish the 8-metric dashboard

Rule:

- do not expand scope until these six items are stable

## 12. Operating conclusion

The strategic move is not to make workers smarter first.

The strategic move is to industrialize the already-stable flows:

- report refresh
- demo rebuild
- ToyOS harness
- artifact audit

When those flows become predictable, MetaForge shifts from:

- "a system that can keep running"

to:

- "a production system that reliably emits verified artifacts"

