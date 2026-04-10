# Token Efficiency Sampling Note

Date: 2026-03-15

Issue 1: lane-mix scoring switched to the 1 hour recent window whenever any recent call existed.

Impact:
- A single recent reasoning call could make `reasoning_ratio` appear as 1.0.
- Autonomy reports could misread token efficiency and lane balance.

Rule:
- Only trust the recent window when `recent_window.total_calls >= ratio_sample_min_calls`.
- Otherwise score lane mix from the full tracking window.

Issue 2: updating telemetry code on disk is not enough when the orchestrator API is already running.

Impact:
- Live tasks can continue writing old-format usage events with no `input_chars` or `output_chars`.
- Output-input ratio remains a fallback placeholder even after code changes are present on disk.

Rule:
- After changing live telemetry or planner fallback code, run a controlled service restart before collecting a validation sample.

Follow-up:
- Keep usage telemetry writing `input_chars` and `output_chars` so output-input ratio becomes a measured signal instead of a fallback default.
- Avoid generic `pytest` fallback validation for bounded artifact-only tasks.
