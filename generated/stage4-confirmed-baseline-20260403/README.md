# Stage 4 Confirmed Baseline

Captured at `2026-04-03T14:32Z` from the first confirmed Stage 4 state.

## Purpose

This package is the point-in-time evidence bundle for the first verified `stage4_confirmed` baseline.

## Included Evidence

- `kernel_mode.json`
- `control_layer_status.json`
- `autonomy_score.json`
- `artifact_registry.json`
- `reality_dashboard.json`
- `release_operations_status.json`
- `autonomy-soak-evidence/`
- `snapshot-manifest.json`

## Baseline Rule

This baseline is valid only while the included evidence remains unchanged. If any source file changes, capture a new baseline package instead of overwriting this one.

## Notes

- The manifest includes SHA256 hashes for the captured files.
- The `autonomy-soak-evidence/` directory is copied in full.
- This bundle is intended for audit, promotion review, and regression comparison.
