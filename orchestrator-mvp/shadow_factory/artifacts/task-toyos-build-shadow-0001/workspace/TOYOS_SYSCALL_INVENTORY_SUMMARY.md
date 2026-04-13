# ToyOS Syscall Inventory Summary

Scope: only `D:\codex\generated\toy-os-demo`

Do not modify:

- `D:\codex\orchestrator-mvp\app`
- `D:\codex\orchestrator-mvp\runtime`
- `D:\codex\orchestrator-mvp\tools`
- MetaForge OS control or routing logic

## Goal

Summarize the current ToyOS syscall surface, its actual in-kernel behavior, current user-mode consumers, and the most important gaps before the syscall layer can support stronger userland and virtual-memory work.

## Current syscall table

Observed from [`include/syscall.h`](D:\codex\generated\toy-os-demo\include\syscall.h):

1. `SYSCALL_WRITE_LOG = 1`
2. `SYSCALL_YIELD = 2`
3. `SYSCALL_EXIT = 3`
4. `SYSCALL_QUERY_PID = 4`
5. `SYSCALL_CONSOLE_WRITE = 5`
6. `SYSCALL_READ_KEY = 6`
7. `SYSCALL_QUERY_TICKS = 7`
8. `SYSCALL_QUERY_HEAP_USED = 8`
9. `SYSCALL_QUERY_PAGES_USED = 9`
10. `SYSCALL_RAMFS_COUNT = 10`
11. `SYSCALL_TINYFS_COUNT = 11`
12. `SYSCALL_RAMFS_NAME = 12`
13. `SYSCALL_TINYFS_NAME = 13`
14. `SYSCALL_RAMFS_READ = 14`
15. `SYSCALL_TINYFS_READ = 15`

The dispatch path is `int 0x80` through [`src/syscall.c`](D:\codex\generated\toy-os-demo\src\syscall.c).

## Current behavior categories

### Process control

- `SYSCALL_YIELD`
  - requests cooperative yield through `scheduler_yield_current()`
  - forces a ring0 return request
- `SYSCALL_EXIT`
  - marks current process exited with an exit code
  - forces a ring0 return request

Status:

- implemented and actively used
- still tied to the current teaching return path rather than a fully preemptive resume model

### Identity and runtime counters

- `SYSCALL_QUERY_PID`
- `SYSCALL_QUERY_TICKS`
- `SYSCALL_QUERY_HEAP_USED`
- `SYSCALL_QUERY_PAGES_USED`

Status:

- implemented
- read-only introspection
- useful for shell and diagnostics

### Console and logging

- `SYSCALL_CONSOLE_WRITE`
  - writes directly to the VGA terminal path
- `SYSCALL_WRITE_LOG`
  - writes to debug output
  - writes the last log string to `proc/syscall.last` in RAMFS

Status:

- implemented
- currently the main user-visible side-effect path for ring3 demos and debug markers

### Input

- `SYSCALL_READ_KEY`
  - returns next buffered keyboard character
  - returns failure sentinel when no input is available

Status:

- implemented
- sufficient for the current interactive teaching shell
- not yet wrapped in a richer terminal or line-editing abstraction

### VFS enumeration and read-only inspection

- `SYSCALL_RAMFS_COUNT`
- `SYSCALL_TINYFS_COUNT`
- `SYSCALL_RAMFS_NAME`
- `SYSCALL_TINYFS_NAME`
- `SYSCALL_RAMFS_READ`
- `SYSCALL_TINYFS_READ`

Status:

- implemented
- these are the newest additions to the syscall surface
- they allow user mode to enumerate file names and read file contents from both teaching filesystems

## Current user-mode consumers

Observed from [`kernel.c`](D:\codex\generated\toy-os-demo\kernel.c):

### User shell

The ring3 shell currently depends on:

- `SYSCALL_CONSOLE_WRITE`
- `SYSCALL_QUERY_PID`
- `SYSCALL_QUERY_TICKS`
- `SYSCALL_QUERY_HEAP_USED`
- `SYSCALL_QUERY_PAGES_USED`
- `SYSCALL_RAMFS_COUNT`
- `SYSCALL_TINYFS_COUNT`
- `SYSCALL_RAMFS_NAME`
- `SYSCALL_TINYFS_NAME`
- `SYSCALL_RAMFS_READ`
- `SYSCALL_TINYFS_READ`
- `SYSCALL_READ_KEY`
- `SYSCALL_YIELD`
- `SYSCALL_EXIT`

This means the shell now exercises more than simple telemetry; it verifies a minimum user-to-kernel filesystem inspection path.

### User probe

The startup `user-probe` process currently depends on:

- `SYSCALL_CONSOLE_WRITE`
- `SYSCALL_WRITE_LOG`
- `SYSCALL_RAMFS_COUNT`
- `SYSCALL_TINYFS_COUNT`
- `SYSCALL_TINYFS_NAME`
- `SYSCALL_TINYFS_READ`
- `SYSCALL_RAMFS_READ`
- `SYSCALL_EXIT`

This makes it the current automatic syscall smoke process.

## Return contract and error style

Current syscall return style in [`src/syscall.c`](D:\codex\generated\toy-os-demo\src\syscall.c):

- success commonly returns `0`
- value-returning syscalls return the requested value directly
- generic invalid-argument failure commonly returns `TOYOS_SYSCALL_STATUS_INVALID` (`0xFFFFFFFFu`)
- lookup or backend failure commonly returns `TOYOS_SYSCALL_STATUS_FAULT` (`0xFFFFFFFEu`)

This contract is usable for the current teaching shell, but it is still ad hoc.

Current limitation:

- the shared symbolic error-code layer now exists in `include/syscall.h`
- failure meanings are still split between invalid input and backend fault paths

## Pointer-safety status

This is the most important current syscall risk.

Observed behavior:

- pointer-bearing syscalls generally check for null pointers only
- the kernel then dereferences user-provided addresses directly
- there is no address-range validation, user-space copy helper, or page-permission check yet

Implication:

- this is now slightly stronger because paged mode rejects pointers outside the current mapped user-accessible window
- it is still insufficient for true protected user memory because the current page tables remain globally user-mapped

## What the current syscall layer can honestly claim

It can honestly claim:

- verified ring3 entry through `int 0x80`
- user-driven console output
- cooperative user yield and exit
- basic runtime introspection
- keyboard polling
- read-only inspection of RAMFS and TinyFS from user mode
- a stable automatic user-probe marker for regression smoke

It cannot yet honestly claim:

- fully safe arbitrary user-pointer handling
- user-mode file creation or file writing
- memory mapping
- process spawning from executable images
- ELF loading through a syscall ABI
- blocking wait primitives
- stable timer-preemptive user scheduling semantics

## Missing syscall families for the next stages

### Stage next: writable filesystem ABI

Recommended future syscall families:

- create file
- write file text or bytes
- append log or stream output to file
- optional directory listing abstraction instead of separate count/name pairs

Why:

- current user mode can inspect files but cannot create a meaningful persistent workflow

### Stage next: safer memory ABI

Recommended future syscall families:

- allocate user pages or regions
- map or unmap memory
- copy-safe kernel-to-user and user-to-kernel helpers behind the syscall layer

Why:

- paging and address-space isolation will require a real boundary between kernel pointers and user pointers

### Stage next: program loading ABI

Recommended future syscall families:

- spawn process from image or path
- query process state
- wait for child exit

Why:

- current user processes are still kernel-registered C entry points
- an ELF loader path needs a syscall surface that userland and loaders can actually target

## Recommended cleanup before expansion

1. Named syscall error codes now exist in the shared header and should remain stable.
2. Separate pure value-return syscalls from status-return plus out-buffer syscalls in the documentation.
3. Grow the current user-pointer validation stub into a real paging-aware boundary check before promoting paged ring3 execution.
4. Keep the current read-only VFS syscalls stable while new write-oriented calls are added separately.
5. Avoid ABI churn in existing shell-visible numbers unless there is a strong teaching reason.

## Suggested next syscall milestone

The next practical syscall milestone for ToyOS should be:

- keep syscall numbers `1-15` stable
- add a minimal writable file path
- add one invalid-syscall regression case
- document pointer-safety limits before enabling any paging smoke path

That sequence extends actual userland usefulness without pretending the kernel already has protected user memory.
