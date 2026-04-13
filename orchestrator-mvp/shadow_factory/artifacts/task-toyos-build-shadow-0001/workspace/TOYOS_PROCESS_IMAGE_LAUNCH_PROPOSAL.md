# ToyOS Process Image Launch Proposal

Scope: only `D:\codex\generated\toy-os-demo`

Do not modify:

- `D:\codex\orchestrator-mvp\app`
- `D:\codex\orchestrator-mvp\runtime`
- `D:\codex\orchestrator-mvp\tools`
- MetaForge OS control or routing logic

## Goal

Define the minimum scheduler-facing proposal that allows ToyOS to launch a user process from a prepared executable image record instead of only from a kernel-linked C function.

This proposal sits between the ELF loader branch goal and any future loader implementation.
Its purpose is to prevent the scheduler ABI from being stretched in an ad hoc way.

## Current scheduler reality

Observed from [`src/scheduler.c`](D:\codex\generated\toy-os-demo\src\scheduler.c) and [`include/scheduler.h`](D:\codex\generated\toy-os-demo\include\scheduler.h):

- `scheduler_create_process(...)` accepts a `process_entry_t entry` and `void* context`
- `process->entry_point` is currently the kernel function pointer cast to an address
- user-mode dispatch still flows through `scheduler_enter_user_process(pid)`
- user-mode handoff uses `scheduler_iret_to_user(entry, user_stack, arg)`
- for user tasks, the `arg` is currently the process context pointer supplied by the kernel
- each process gets one kernel stack and, for user tasks, one user stack page
- the scheduler does not yet track image ownership, image base, segment count, or address-space metadata

Implication:

- the current process model is a kernel-task model with a ring3 teaching handoff, not yet an external program model

## Problem to solve

The current ABI conflates two different things:

1. kernel dispatch entry
2. user instruction pointer to begin execution at

That is acceptable when user tasks are compiled-in C functions, but it will become brittle once the user entry point comes from a loaded image.

A new abstraction is needed so ToyOS can say:

- the kernel knows how to schedule this process
- the user image should begin at this entry address
- this image owns these memory pages
- this launch is derived from a loadable file, not a kernel symbol

## Proposed abstraction

Introduce a `process_image_launch_t` record.

Suggested fields:

- `const char* image_name`
- `uintptr_t entry_address`
- `uintptr_t user_stack_top`
- `uintptr_t image_base`
- `uintptr_t image_limit`
- `uint32_t image_page_count`
- `void* bootstrap_context`
- `uint8_t valid`

Purpose of each field:

- `image_name`
  - stable human-readable debug label
- `entry_address`
  - actual user instruction pointer for `iret` handoff
- `user_stack_top`
  - initial ring3 stack top
- `image_base` and `image_limit`
  - teaching-level memory ownership bounds
- `image_page_count`
  - accounting and later cleanup support
- `bootstrap_context`
  - optional loader or launch metadata visible to the kernel side
- `valid`
  - explicit ready-to-launch gate

## Proposed scheduler evolution

### Keep existing path intact

Do not break the current teaching API immediately:

- keep `scheduler_create_process(...)` working for kernel tasks and existing user-shell style tasks

Why:

- current repo stability depends on the existing compiled-in user process model

### Add a second creation path

Introduce one of the following:

- `scheduler_create_process_from_image(...)`
- or `scheduler_create_image_process(...)`

Suggested parameters:

- process name
- launch record pointer
- privilege
- priority
- time slice

Expected behavior:

- allocate kernel stack
- validate launch record
- attach user stack and launch metadata
- store image entry address separately from any kernel bootstrap hook
- mark process as ring3-launchable only if the launch record is valid

### Extend `process_t`

Recommended additions to [`process_t`](D:\codex\generated\toy-os-demo\include\scheduler.h):

- `uintptr_t user_entry_point`
- `uintptr_t image_base`
- `uintptr_t image_limit`
- `uint32_t image_page_count`
- `uint8_t launch_kind`

Suggested `launch_kind` values:

- `kernel_entry`
- `user_compiled_stub`
- `user_loaded_image`

Why:

- this avoids overloading the existing `entry_point` field with contradictory meanings

## Dispatch proposal

### Existing behavior to preserve

For existing compiled-in user tasks:

- user dispatch should still be able to hand off to the current entry address

### New image-launch behavior

For loaded-image tasks:

- dispatch should use `user_entry_point`, not a kernel function pointer
- `scheduler_iret_to_user(...)` should receive:
  - image entry address
  - prepared user stack top
  - optionally a bootstrap argument only if the ABI explicitly allows it

Important design note:

- the first external image ABI should avoid pretending arbitrary C-style `void* context` is a stable user ABI
- for the first loaded image path, it is cleaner if user code starts with no implicit pointer contract unless one is deliberately defined

## Memory ownership proposal

Current allocator reality from [`src/memory.c`](D:\codex\generated\toy-os-demo\src\memory.c):

- page allocator is fixed-size
- total pages are limited
- there is no advanced ownership metadata

Minimum proposal:

- the loader must count how many pages were reserved for the image
- the process record should retain that count and image range
- process teardown should eventually release image pages in addition to stack pages

This is still a teaching-level ownership model, but it is enough to avoid leaking all loaded-image allocations silently.

## Failure model

The new launch path should fail explicitly for at least these cases:

- null launch record
- invalid launch record
- zero entry address
- zero user stack top
- image range inversion or empty image range
- kernel stack allocation failure
- user stack allocation failure
- image page exhaustion

Recommended outcome:

- process creation returns `0` or a clear failure signal
- debug marker explains which validation gate failed

## Suggested debug markers

For a first implementation, require markers such as:

- `SCHED: image launch validate begin`
- `SCHED: image launch accepted`
- `SCHED: image process created`
- `SCHED: dispatch image user`
- `SCHED: image user returned`

Failure markers:

- `SCHED: image launch rejected`
- `SCHED: image stack alloc failed`
- `SCHED: image metadata invalid`

## Non-goals for this proposal

This proposal does not require:

- per-process page directories
- relocation support
- dynamic linker support
- user-space argv/envp model
- full execve semantics
- process forking
- stable parent/child wait model

Those can come later.

## Recommended implementation order

1. Extend `process_t` with image-launch metadata.
2. Add a launch-record type in a scheduler-facing header.
3. Add a second process-creation API for image-based user launches.
4. Keep dispatch logic explicit about whether a process is using compiled-in user entry or loaded-image entry.
5. Add temporary debug markers before claiming a working ELF loader path.

## Acceptance criteria

This proposal is complete only if all of the following are true:

1. It explains why the current `scheduler_create_process(...)` shape is insufficient for loaded images.
2. It introduces a concrete launch-record abstraction.
3. It defines the minimum `process_t` metadata additions needed for image-based processes.
4. It records a failure model instead of assuming all loads are valid.
5. It preserves the existing compiled-in user-task path as a compatibility lane.

## Recommended next artifact

After this proposal, the next strongest ToyOS artifact should be either:

1. `TOYOS_ELF_FORMAT_NOTE.md`
2. `TOYOS_IMAGE_PROCESS_PATCH_PROPOSAL.md`

That keeps implementation work disciplined: first define the executable contract, then define the scheduler patch surface that consumes it.
