ToyOS mainline capability task: deliver guarded paging with user address-space isolation.

Scope:
- Make paging real on the mainline path.
- Split kernel and user address spaces.
- Keep user-buffer validation safe under the new memory model.
- Preserve the existing scheduler and user demo behavior as the paging work progresses.

Expected delivery:
- Source changes under `D:\codex\generated\toy-os-demo` for paging, memory, syscall, and any required headers.
- Refreshed evidence showing the guarded paging path was exercised.
- A brief implementation note describing the kernel/user split and address-space model.

Acceptance:
- Kernel still builds.
- User processes run with the guarded paging path enabled.
- User buffer validation remains correct under the new memory model.
- Kernel-only mappings remain separated from user-accessible mappings.

Constraints:
- Treat this as the hard mainline capability path.
- Keep the first version incremental and reviewable.
- Do not claim general virtual memory completeness if the implementation is still a bounded stage.
