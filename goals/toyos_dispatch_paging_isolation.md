ToyOS P0 task: stabilize experimental paging and turn it into the default protected path.

Scope:
- Promote the current experimental paging path into the stable path.
- Implement real virtual address space isolation between kernel and user processes.
- Ensure user buffers validated by syscalls cannot escape their mapped user ranges.
- Preserve the existing scheduler/syscall/user-shell demo behavior after the paging change.

Expected delivery:
- Source changes under D:\codex\generated\toy-os-demo for paging, memory, scheduler, syscall, and any required headers.
- Refreshed machine-readable evidence under D:\codex\generated\toy-os-demo showing build/test impact.
- A brief implementation note describing the address-space model and kernel/user split.

Acceptance:
- Kernel still builds.
- User processes can run after paging is enabled by default.
- Syscall buffer validation remains correct under the new virtual memory model.
- The implementation clearly separates kernel-only mappings from user-accessible mappings.

Constraints:
- Treat this as the top-priority ToyOS task.
- Do not replace the problem with stubs or comments-only changes.
- Prefer an incremental, reviewable design over a speculative full MMU rewrite.
