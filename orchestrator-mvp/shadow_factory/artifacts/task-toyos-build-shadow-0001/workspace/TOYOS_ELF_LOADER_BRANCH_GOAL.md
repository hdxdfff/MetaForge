# ToyOS ELF Loader Branch Goal

Scope: only `D:\codex\generated\toy-os-demo`

Do not modify:

- `D:\codex\orchestrator-mvp\app`
- `D:\codex\orchestrator-mvp\runtime`
- `D:\codex\orchestrator-mvp\tools`
- MetaForge OS control or routing logic

## Goal

Define the minimum realistic path from the current ToyOS teaching kernel to a first user-mode ELF loading flow.

This branch goal is intentionally scoped as a staged design and implementation boundary.
It does not claim that the current kernel is one patch away from full executable loading.

## Current kernel facts

Observed from the current codebase:

- user processes are currently created by the kernel through `scheduler_create_process(...)`
- user processes execute kernel-linked C entry points, not external binaries
- the scheduler prepares one kernel stack and one user stack per user process
- there is no per-process page directory or address-space object yet
- paging code exists, but is disabled in the stable boot path
- syscall support is currently focused on console, process control, telemetry, keyboard input, and read-only VFS inspection
- TinyFS and RAMFS can expose file contents to user mode, but there is no binary loader path
- the build currently produces a single kernel image and optional GRUB ISO, not separate user-program artifacts

## Why ELF loading is not a direct next-line feature

A true user-mode ELF loader depends on multiple capabilities that do not yet exist together:

1. Executable file format parsing in the kernel or a trusted loader layer.
2. A way to allocate and place code/data segments into a user-owned memory region.
3. A process model that can start at an executable entry address rather than a kernel C function symbol.
4. Clear user-pointer and copy boundaries.
5. Eventually, per-process address-space ownership.

Because those pieces are missing, the first useful ELF milestone must be staged.

## Proposed staged path

### Stage 0: document and isolate prerequisites

Deliverables:

- syscall inventory note for current ABI reality
- paging branch goal documenting why user isolation is not ready yet
- ELF loader branch goal documenting staged promotion conditions

Exit condition:

- repo clearly states what is missing before external user programs are realistic

### Stage 1: define a minimal executable-loading contract

Goal:

- introduce a ToyOS-specific first executable contract without yet requiring full process isolation

Recommended boundary:

- support only 32-bit little-endian ELF executables
- support only statically laid out, non-relocatable user images for the first step
- accept a very small subset of ELF fields needed to validate header, program entry, and loadable segments
- reject unsupported binaries loudly

Deliverables:

- ELF format note for ToyOS
- validation rules for accepted headers and segments
- explicit failure codes for invalid image, unsupported image, and resource exhaustion

Exit condition:

- the repo defines what qualifies as a loadable user image

### Stage 2: create a kernel-side image loader scaffold

Goal:

- parse a user image from TinyFS or RAMFS and prepare an execution record without yet claiming stable isolated execution

Minimum implementation ideas:

- read executable bytes from TinyFS
- validate ELF magic and basic header layout
- identify entry point and loadable segments
- allocate memory pages for the image payload using the current page allocator
- copy segment bytes into allocated pages
- build a process launch record containing:
  - entry address
  - initial user stack top
  - image base metadata

Exit condition:

- the kernel can load a known-good teaching executable image into memory and produce a launch-ready record

Important limitation:

- until process address spaces exist, this remains a loader scaffold, not a strong security boundary

### Stage 3: extend process creation beyond C entry points

Goal:

- let the scheduler create a user process from a prepared executable launch record instead of only from a kernel function pointer

Required scheduler evolution:

- a process creation path that accepts user entry address separately from kernel-internal bootstrap helpers
- metadata fields for image ownership and launch origin
- a clear distinction between:
  - kernel task entry function
  - user image entry address

Deliverables:

- scheduler branch that can launch a prepared user image
- debug markers proving control reached the expected image entry

Exit condition:

- ToyOS can start a first external user image in a controlled teaching path

### Stage 4: tighten memory and syscall boundaries

Goal:

- make ELF loading compatible with future paged isolation instead of locking in unsafe assumptions

Required improvements:

- symbolic syscall error codes
- user-pointer validation plan
- safe copy-in and copy-out helpers
- initial address-space ownership model for each process

Exit condition:

- executable loading no longer assumes kernel-equivalent pointer trust

## First realistic non-goals

The first ELF branch must not try to solve all of these at once:

- dynamic linking
- shared libraries
- relocation-heavy binaries
- demand paging
- copy-on-write
- full POSIX process model
- complex virtual memory manager
- multi-binary package management

Trying to add those before the first teaching executable path will over-expand the branch.

## Required interfaces before promotion

### Filesystem side

At least one of these must become true:

- a kernel-internal loader can read raw executable bytes from TinyFS directly
- or a new syscall family can expose image-loading requests cleanly

For the first branch, kernel-internal file loading is simpler and less disruptive.

### Scheduler side

At least one new process-launch abstraction is needed:

- `create_process_from_image(...)`
- or an equivalent launch-record based helper

The current `scheduler_create_process(...)` shape is tied to a kernel function pointer and is not sufficient by itself.

### Memory side

At minimum:

- page allocator ownership for loaded image pages must be tracked conceptually
- loader code must document where code, data, and user stack live

Eventually:

- per-process address spaces should replace shared assumptions

## Validation plan

### Static validation

Confirm that the branch defines:

- accepted ELF subset
- loader failure cases
- process-launch handoff structure
- explicit non-goals

### Runtime teaching validation

For the first runnable ELF milestone, require markers such as:

- `ToyOS: elf load begin`
- `ToyOS: elf validated`
- `ToyOS: elf segments loaded`
- `ToyOS: elf process launched`
- user-visible marker from the loaded image itself

### Failure validation

Require explicit failure markers for:

- bad ELF magic
- unsupported architecture or class
- malformed segment layout
- out-of-pages or out-of-memory
- launch handoff failure

## Acceptance criteria for this branch goal

This ELF loader branch goal is complete only if all of the following are true:

1. The repo clearly states that current user tasks are kernel-linked C functions.
2. The missing prerequisites for external program loading are explicitly listed.
3. A staged implementation path exists from format validation to launch handoff.
4. Scheduler and memory implications are recorded instead of hidden.
5. Validation markers and failure cases are defined before implementation claims begin.

## Recommended next step after this branch goal

After this document, the next strongest ToyOS artifact should be one of:

1. `TOYOS_ELF_FORMAT_NOTE.md`
2. `TOYOS_PROCESS_IMAGE_LAUNCH_PROPOSAL.md`
3. a minimal patch proposal for adding a non-default `create_process_from_image` scaffold

That keeps ELF work aligned with actual kernel maturity instead of skipping directly to a loader that the current process model cannot safely support.
