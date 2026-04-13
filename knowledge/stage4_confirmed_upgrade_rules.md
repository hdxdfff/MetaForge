# Stage 4 Confirmed Upgrade Rules

## Goal

Prevent future promotion decisions from relying on score alone. `stage4_confirmed` must be justified by live evidence, a stable control layer, and at least one new real technical artifact.

## Minimum Conditions For `stage4_confirmed`

Promotion is valid only when all of the following are true:

1. `kernel_mode.profile == "standard"`
2. `control_layer_status == "stable"`
3. `autonomy_score.stage == "stage4_confirmed"`
4. `autonomy_score.decision.stable_autonomy == true`
5. `autonomy_score.decision.needs_more_soak == false`
6. `autonomy_score.signal_policy.release_gate_signal_count == 0`
7. `artifact_registry.status == "pass"`
8. `reality_dashboard.status == "pass"`
9. `release_operations.status == "pass"`
10. At least one new real, executable, self-tested, auditable technical artifact exists in the current evidence window

## Evidence Standards

- Do not treat `score` as a promotion signal by itself.
- Require a fresh artifact manifest or evidence bundle for every new confirmed baseline.
- Require file-level evidence, not only summary-state files.
- Require the artifact to be reproducible or clearly documented as reproducible by design.

## Anti-Gaming Rules

- A higher score without a new real technical artifact does not qualify for promotion.
- A passing release gate without `artifact_registry == pass` does not qualify for promotion.
- A preserved soak confirmation only counts if the current control layer is stable and runtime remains fresh.
- If any of the baseline files drift, the baseline becomes historical evidence only and must not be reused as current state.

## Operational Interpretation

For this workspace, `stage4_confirmed` means:

- the control plane is no longer in `interaction_only`
- the production evidence is real and audit-backed
- the release gate is clear
- the system can preserve confirmed status across restart without losing the evidence chain

## Current Confirmed Baseline Package

The first confirmed baseline package is:

- [`D:\codex\generated\stage4-confirmed-baseline-20260403`](D:\codex\generated\stage4-confirmed-baseline-20260403)

The core evidence pack inside it includes:

- [`kernel_mode.json`](D:\codex\generated\stage4-confirmed-baseline-20260403\kernel_mode.json)
- [`control_layer_status.json`](D:\codex\generated\stage4-confirmed-baseline-20260403\control_layer_status.json)
- [`autonomy_score.json`](D:\codex\generated\stage4-confirmed-baseline-20260403\autonomy_score.json)
- [`artifact_registry.json`](D:\codex\generated\stage4-confirmed-baseline-20260403\artifact_registry.json)
- [`reality_dashboard.json`](D:\codex\generated\stage4-confirmed-baseline-20260403\reality_dashboard.json)
- [`release_operations_status.json`](D:\codex\generated\stage4-confirmed-baseline-20260403\release_operations_status.json)
- [`autonomy-soak-evidence/`](D:\codex\generated\stage4-confirmed-baseline-20260403\autonomy-soak-evidence)
