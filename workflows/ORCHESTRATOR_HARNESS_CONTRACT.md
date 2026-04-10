# Orchestrator / Harness Contract

## Scope

This contract defines the separation between task orchestration and delivery governance in MetaForge OS.

## Orchestrator

Responsible for:

- goal intake and decomposition
- task packet creation
- executor selection and dispatch
- context reduction for executors
- task queue management

Must not:

- issue release decisions
- assert pass/fail on delivery
- inspect executor internals beyond required contract fields
- mutate audit ledgers as a substitute for verification

## Harness

Responsible for:

- contract validation
- evidence validation
- runtime result verification
- risk classification
- release gating
- rollback eligibility
- audit ledger updates

Must not:

- rewrite task scope after execution starts
- depend on executor private context for conclusions
- mark a delivery pass without evidence
- act as the task planner

## Context separation

The orchestrator and harness must use separate context products:

- `execution_context`: reduced task packet, execution constraints, and dispatch metadata
- `verification_context`: runtime reports, evidence digests, and evaluator outputs
- `audit_context`: immutable decision records, incident classification, and release gate state

The harness may read the outputs of the execution layer, but it must not consume the executor's long-form reasoning trace as an input of record.

## State model

Minimum governance states:

- `planned`
- `dispatched`
- `generating`
- `candidate_ready`
- `evaluating`
- `pass`
- `fail`

Minimum governance outputs:

- `sprint_contract`
- `evaluation_report`
- `artifact_registry_entry`
- `audit_record`
- `release_decision`

## Evidence rule

No delivery may be declared complete without:

- a contract
- a runtime/evidence record
- an evaluation result
- an audit record

## Incident handling

If runtime continuity is preserved but the quality plane regresses, classify the event separately from execution failure.

Use the incident class:

- `quality_plane_regression_without_runtime_continuity_loss`

This preserves the distinction between:

- runtime continuity
- release readiness
- self-model health

## Operator rule

Orchestrator changes should favor dispatch and context shaping.
Harness changes should favor verification, release control, and ledger integrity.
