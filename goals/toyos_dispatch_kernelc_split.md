ToyOS architecture task: split `kernel.c` into smaller implementation units.

Scope:
- Move startup probe logic out of `kernel.c`.
- Move user-mode probe logic out of `kernel.c`.
- Move debug output code out of `kernel.c`.
- Move image/load flow code out of `kernel.c`.
- Move demo-only logic out of `kernel.c`.

Expected delivery:
- Source changes under `D:\codex\generated\toy-os-demo` that reduce `kernel.c` to a thin coordinator.
- A brief implementation note describing the new module boundaries.
- Refreshed evidence showing the refactor preserved the boot contract.

Acceptance:
- `kernel.c` is materially smaller and no longer owns all non-core flows.
- Startup probe, user probe, debug output, image/load, and demo logic are separated into their own modules or source units.
- The default boot path remains stable.

Constraints:
- Keep the change incremental and reviewable.
- Do not replace the refactor with comments-only or stub-only changes.
- Preserve existing ToyOS behavior while the split is in progress.
