# ToyOS Writable File Syscall Patch Proposal

Scope: only `D:\codex\generated\toy-os-demo`

Do not modify:

- `D:\codex\orchestrator-mvp\app`
- `D:\codex\orchestrator-mvp\runtime`
- `D:\codex\orchestrator-mvp\tools`
- MetaForge OS control or routing logic

## Goal

Describe the minimum syscall patch that lets ToyOS user mode create or overwrite simple text files in RAMFS and TinyFS.

This proposal is intentionally narrow.
It aims to unlock basic userland workflow value without pretending the kernel already has safe user-memory isolation.

## Why this is the right next syscall step

Observed from the current codebase:

- the syscall layer already supports file enumeration and read-only inspection
- the VFS layer already exposes `ramfs_create`, `ramfs_write_text`, `tinyfs_create`, and `tinyfs_write_text`
- user mode currently cannot persist any work product
- current user shell can inspect the filesystem, but cannot create a file, write a note, or update a log

That means the smallest useful extension is not `mmap` or `spawn`, but a writable-file syscall path.

## Proposed syscall additions

Recommended additions in [`include/syscall.h`](D:\codex\generated\toy-os-demo\include\syscall.h):

- `SYSCALL_RAMFS_WRITE = 16`
- `SYSCALL_TINYFS_WRITE = 17`
- optional later: `SYSCALL_RAMFS_CREATE = 18`
- optional later: `SYSCALL_TINYFS_CREATE = 19`

For the minimum patch, explicit create syscalls are not strictly necessary because current VFS write helpers already create the file if missing.

## Recommended ABI shape

### Write text syscalls

Suggested call shape:

- `arg0 = path pointer`
- `arg1 = text pointer`
- `arg2 = text buffer capacity or declared length`
- `arg3 = reserved = 0`

Recommended first-step semantics:

- user passes a null-terminated text buffer
- kernel requires non-null `path` and `text`
- `arg2` may be used as a maximum accepted copy length
- if `arg2 == 0`, treat it as invalid for consistency

Return convention:

- `0` on success
- `0xFFFFFFFFu` on invalid argument
- `0xFFFFFFFEu` on backend failure or truncated-reject policy

## Why create and write can be merged for now

Current VFS behavior already does this:

- `ramfs_write_text(...)` creates a file if it does not exist
- `tinyfs_write_text(...)` creates a file if it does not exist

So the syscall layer can stay minimal by exposing write-first semantics and postponing explicit create-only syscalls.

This keeps the ABI small while still enabling userland to persist text.

## Proposed kernel-side patch surface

Files expected to change in the future implementation branch:

- [`include/syscall.h`](D:\codex\generated\toy-os-demo\include\syscall.h)
- [`src/syscall.c`](D:\codex\generated\toy-os-demo\src\syscall.c)
- optionally [`kernel.c`](D:\codex\generated\toy-os-demo\kernel.c) if the teaching shell is extended with write commands

No platform-control files are in scope.

## Suggested `src/syscall.c` behavior

Add two new switch cases:

- `SYSCALL_RAMFS_WRITE`
- `SYSCALL_TINYFS_WRITE`

Minimum validation:

- reject null path pointer
- reject null text pointer
- reject zero `arg2`

Minimum backend behavior:

- call `ramfs_write_text(...)` or `tinyfs_write_text(...)`
- return `0` on success
- return `0xFFFFFFFEu` on filesystem failure

## Important limitation to document honestly

This patch does not solve safe user-buffer copying.

Current syscall limitation still applies:

- the kernel will still be dereferencing user-provided pointers directly
- this remains acceptable only because ToyOS stable path still lacks real paged user isolation

Therefore this patch proposal must ship with an explicit note:

- writable file syscalls are a teaching-step ABI, not a hardened memory-safety boundary

## Recommended shell follow-up

Once the syscall cases exist, the next teaching-shell extension can be small.

Recommended commands:

- `write ramfs <path> <text>`
- `write tinyfs <path> <text>`

Why:

- this demonstrates real user-mode state change
- it makes the shell more useful without needing a full editor or binary upload path

This shell work can be a follow-up patch, not part of the minimum syscall patch itself.

## Suggested debug markers

Temporary markers for the first implementation:

- `SYSCALL: ramfs write requested`
- `SYSCALL: tinyfs write requested`
- `SYSCALL: fs write ok`
- `SYSCALL: fs write failed`

These help early QEMU smoke runs confirm behavior before richer regression harnesses exist.

## Validation plan

### Static validation

Confirm that the implementation branch does all of the following:

- adds syscall numbers without renumbering `1-15`
- adds write switch cases in `src/syscall.c`
- keeps existing read-only syscalls unchanged

### Runtime validation

First-stage runtime validation should prove:

- a user task can write a new RAMFS file
- a user task can write a new TinyFS file
- a later read syscall can fetch the just-written content

Recommended smoke sequence:

1. call new RAMFS write syscall for a path such as `tmp/user-note`
2. read the same path through existing RAMFS read syscall
3. call new TinyFS write syscall for a path such as `usr/session.txt`
4. read the same path through existing TinyFS read syscall

### Regression safety validation

Must also confirm:

- existing `ls` still works
- existing `cat <path>` still works
- `user-probe` still completes
- stable boot path remains unchanged

## Non-goals

This patch proposal does not include:

- byte-range writes
- append mode
- directories
- file deletion
- binary-safe write ABI
- pointer validation overhaul
- mmap or shared memory

Those can come later.

## Acceptance criteria

This proposal is complete only if all of the following are true:

1. It defines a minimal syscall-number expansion path.
2. It reuses existing VFS write capability instead of inventing a larger ABI than needed.
3. It records the current pointer-safety limitation explicitly.
4. It defines a concrete read-after-write validation flow.
5. It keeps existing syscall numbers `1-15` stable.

## Recommended next step

After this proposal, the strongest next ToyOS step is either:

1. a real implementation branch for `SYSCALL_RAMFS_WRITE` and `SYSCALL_TINYFS_WRITE`
2. a small shell patch adding `write ramfs` and `write tinyfs`
3. an invalid-syscall regression test note so ABI growth is matched by error-path coverage
