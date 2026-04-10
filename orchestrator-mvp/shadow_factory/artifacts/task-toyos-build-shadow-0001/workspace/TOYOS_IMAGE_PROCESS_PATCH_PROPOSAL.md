# ToyOS Image Process Patch Proposal

Scope: only `D:\codex\generated\toy-os-demo`

Do not modify:

- `D:\codex\orchestrator-mvp\app`
- `D:\codex\orchestrator-mvp\runtime`
- `D:\codex\orchestrator-mvp\tools`
- MetaForge OS control or routing logic

## Goal

Describe the minimum patch set that upgrades the ToyOS scheduler from a compiled-entry-only user task model to a dual-path model that can also host image-based user launches.

This is a scheduler and metadata proposal, not yet an ELF parser proposal.

## Why this patch should happen before a loader patch

Current reality from [`src/scheduler.c`](D:\codex\generated\toy-os-demo\src\scheduler.c):

- user launch still depends on `process->entry_point` holding a kernel-known entry symbol
- user dispatch always calls `scheduler_iret_to_user(process->entry_point, process->user_stack_top, process->context)`
- the current `process_t` does not express whether the entry address came from a compiled stub or a loaded image

If a loader is added before this distinction exists, the scheduler ABI will become ambiguous and fragile.

## Proposed patch surface

Files expected to change in the future implementation branch:

- [`include/scheduler.h`](D:\codex\generated\toy-os-demo\include\scheduler.h)
- [`src/scheduler.c`](D:\codex\generated\toy-os-demo\src\scheduler.c)
- optionally a new loader-facing header such as `include/process_image.h`

No platform-control or factory files are in scope.

## Patch 1: extend scheduler metadata

### Add launch-kind enum

Recommended addition in [`include/scheduler.h`](D:\codex\generated\toy-os-demo\include\scheduler.h):

- `PROCESS_LAUNCH_KERNEL_ENTRY`
- `PROCESS_LAUNCH_USER_COMPILED_STUB`
- `PROCESS_LAUNCH_USER_LOADED_IMAGE`

Purpose:

- make the process record explicit about what kind of launch it represents

### Add image-launch record type

Recommended new type:

- `process_image_launch_t`

Suggested fields:

- `const char* image_name`
- `uintptr_t entry_address`
- `uintptr_t user_stack_top`
- `uintptr_t image_base`
- `uintptr_t image_limit`
- `uint32_t image_page_count`
- `void* bootstrap_context`
- `uint8_t valid`

Purpose:

- define one handoff record between any future loader and the scheduler

### Extend `process_t`

Recommended additions:

- `uintptr_t user_entry_point`
- `uintptr_t image_base`
- `uintptr_t image_limit`
- `uint32_t image_page_count`
- `uint8_t launch_kind`

Expected meaning:

- `entry_point`
  - remains the kernel-side entry for current compiled tasks
- `user_entry_point`
  - becomes the actual ring3 instruction pointer for image-based launches
- `launch_kind`
  - tells dispatch which path it is serving

## Patch 2: keep current API stable

Keep `scheduler_create_process(...)` intact for current branches.

Required compatibility behavior:

- kernel tasks continue to use the current function-pointer path
- current user tasks such as `user-shell` and `user-probe` remain launchable without code outside scheduler changes
- current regression markers remain available

Recommended internal cleanup:

- when `scheduler_create_process(...)` is used for a user process, set:
  - `launch_kind = PROCESS_LAUNCH_USER_COMPILED_STUB`
  - `user_entry_point = entry_point`

This creates the new model without forcing immediate call-site churn.

## Patch 3: add image-process creation API

Recommended new function in [`include/scheduler.h`](D:\codex\generated\toy-os-demo\include\scheduler.h):

- `pid_t scheduler_create_process_from_image(const char* name, const process_image_launch_t* launch, uint32_t priority, uint32_t time_slice);`

Expected validation rules:

- `launch != 0`
- `launch->valid != 0`
- `launch->entry_address != 0`
- `launch->user_stack_top != 0`
- `launch->image_limit > launch->image_base`

Expected allocation rules:

- allocate kernel stack as usual
- do not allocate a second synthetic user stack if the launch record already provides one, unless the chosen ABI explicitly wants scheduler-owned stack creation
- attach image metadata to the process record

Expected metadata after success:

- `privilege = PROCESS_PRIVILEGE_USER`
- `launch_kind = PROCESS_LAUNCH_USER_LOADED_IMAGE`
- `user_entry_point = launch->entry_address`
- `image_base = launch->image_base`
- `image_limit = launch->image_limit`
- `image_page_count = launch->image_page_count`
- `ring3_ready = 1`

## Patch 4: update dispatch logic

### Current problematic coupling

Current user dispatch uses:

- `process->entry_point`
- `process->user_stack_top`
- `process->context`

That assumes the ring3 entry and kernel-side process model are the same thing.

### Proposed dispatch split

For `PROCESS_LAUNCH_USER_COMPILED_STUB`:

- keep existing effective behavior
- hand off through `scheduler_iret_to_user(user_entry_point, user_stack_top, context)`

For `PROCESS_LAUNCH_USER_LOADED_IMAGE`:

- hand off through `scheduler_iret_to_user(user_entry_point, user_stack_top, 0)` unless a first-image ABI deliberately defines a bootstrap argument
- do not require `process->entry` to be a kernel C function pointer

Important implementation note:

- `scheduler_dispatch_once()` currently skips processes with `entry == 0`
- that condition must be relaxed for `PROCESS_LAUNCH_USER_LOADED_IMAGE`, otherwise image processes can never dispatch

## Patch 5: teardown and accounting updates

Current teardown only releases stack pages.

Minimum required improvement:

- record image-page ownership metadata in the process
- if actual page ownership release is not implemented yet, add explicit TODO comments and debug markers so image processes do not silently pretend to have full cleanup

Preferred near-term improvement:

- add a helper that can release tracked image pages once the loader defines exactly how pages are allocated and tracked

## Suggested debug markers

Add temporary markers around the new path:

- `SCHED: image create begin`
- `SCHED: image create success`
- `SCHED: image dispatch`
- `SCHED: image user returned`

Failure markers:

- `SCHED: image create rejected`
- `SCHED: image launch invalid`
- `SCHED: image dispatch blocked`

These should stay until a first ELF runtime regression is stable.

## Validation plan

### Static validation

Confirm that the implementation branch does all of the following:

- adds launch-kind metadata
- adds a scheduler-facing image launch record
- preserves current `scheduler_create_process(...)` call sites
- allows user-image processes to dispatch even when `entry == 0`

### Runtime validation

For a first staged implementation, a synthetic image-launch smoke path is enough.

Recommended smoke shape:

- construct a fake `process_image_launch_t` with a known ring3 entry address
- create one image-based user process through the new API
- confirm scheduler emits image-create and image-dispatch markers
- confirm a user-visible marker is printed from the launched image path

### Regression safety validation

Must also confirm:

- current `user-shell` still launches
- current `user-probe` still launches
- current process report still renders
- stable boot path remains with paging disabled

## Explicit non-goals

This patch proposal does not include:

- real ELF parsing
- filesystem image reading
- per-process page tables
- user pointer validation overhaul
- `exec`, `fork`, or `wait`

Those belong to later branches.

## Acceptance criteria

This proposal is complete only if all of the following are true:

1. It defines a concrete scheduler patch surface.
2. It preserves the current compiled-in user-task path.
3. It explicitly handles the `entry == 0` dispatch problem for loaded images.
4. It records both validation and regression-safety expectations.
5. It does not overclaim loader or VM functionality that the current kernel does not have.

## Recommended next artifact

After this proposal, the strongest next ToyOS step is either:

1. `TOYOS_ELF_FORMAT_NOTE.md`
2. a real implementation branch touching only `include/scheduler.h` and `src/scheduler.c`
3. a writable-file syscall patch proposal to keep userland usefulness growing in parallel
