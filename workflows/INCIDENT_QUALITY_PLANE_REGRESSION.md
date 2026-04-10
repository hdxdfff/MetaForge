# Incident Template: Quality-Plane Regression Without Runtime Continuity Loss

Use this template when a historical soak or runtime milestone still stands, but the current live system drops from ready to candidate, degraded, or attention because of quality-gate signals.

## Definition

This incident type means:

- runtime continuity is still preserved
- historical milestone evidence is still valid
- live release readiness has regressed
- self-model or task-health issues may coexist, but they are not automatically the primary trigger

## Required split

Always report these axes separately:

- `runtime:` `preserved | stable | broken`
- `release readiness:` `ready | candidate | degraded`
- `self-model health:` `healthy | attention | blocked`

## Triage

1. Confirm the historical milestone is still `committed` in the milestone ledger.
2. Confirm daemon continuity still holds and tick progression remains fresh.
3. Identify the exact live quality signal that downgraded readiness.
4. Check whether verification now carries a quality-related pending check.
5. Check whether self-model health is independently being dragged down by stalled or misclassified tasks.
6. Classify the quality regression into one of:
   - `capability_regression`
   - `eval_drift`
   - `routing_regression`

## Report format

First section: milestone validity

```text
12h soak conclusion remains valid.
Continuity and historical evidence were not invalidated.
```

Second section: live health regression

```text
Current live readiness has degraded because <trigger_signal>.
runtime: preserved
release readiness: candidate
self-model health: attention
```

Third section: concurrent contributors

```text
Concurrent contributors:
- <stalled task semantics, if any>
- <verification quality pending, if any>
- <routing or evaluator drift suspicion, if any>
```

## Interpretation rule

Do not summarize this incident as "the system regressed" or "the soak failed" unless runtime continuity or milestone evidence actually broke.

Preferred wording:

```text
This is a quality-plane regression with concurrent live-health drag, not a continuity failure.
```
