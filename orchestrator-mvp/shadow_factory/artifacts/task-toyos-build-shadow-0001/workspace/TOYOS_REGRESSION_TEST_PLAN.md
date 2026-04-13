# ToyOS Regression Test Plan

Scope: only `D:\codex\generated\toy-os-demo`

Do not modify:

- `D:\codex\orchestrator-mvp\app`
- `D:\codex\orchestrator-mvp\runtime`
- `D:\codex\orchestrator-mvp\tools`
- MetaForge OS control or routing logic

## Goal

Define the minimum repeatable regression plan for the current ToyOS teaching kernel.

This plan is intentionally staged:

- Stage A covers the currently implemented stable path.
- Stage B covers guarded experiments that are not yet part of the default boot contract.

No item is considered complete unless it has an observable marker, output, or failure condition.

## Current kernel baseline

Observed from the current codebase:

- stable boot path initializes GDT, TSS, IDT, syscall gate, heap/page allocator, VFS, scheduler, timer, keyboard, and ramdisk-backed filesystems
- stable boot path does not enable paging by default
- ring3 user processes are created through `scheduler_create_process(...)`
- current user-facing regression surface includes the user probe, user shell, RAMFS/TinyFS enumeration and reads, and the software interrupt smoke
- current syscall pointer validation now flows through a shared staging stub, but not yet through paging-aware enforcement
- current scheduler exposes priority, states, and time-slice fields, but runtime behavior is still closer to cooperative teaching flow than full preemptive isolation

## Regression principles

1. Keep the default stable boot path green.
2. Separate stable regressions from experimental regressions.
3. Prefer debug markers and deterministic console output over ambiguous visual checks.
4. Record known unsafe gaps instead of silently treating them as passed.
5. If a test depends on paging isolation, timer-preemptive ring3 resume, or validated user pointers, mark it as staged-future instead of pretending it exists now.

## Stage A: stable-path regressions

These checks target the current default boot path and should remain green on every ToyOS branch that claims not to change kernel fundamentals.

### A1 Boot and subsystem bring-up

Expected debug markers:

- `ToyOS: kernel_main entered`
- `ToyOS: GDT and TSS ready`
- `ToyOS: core subsystems initialized`
- `ToyOS: filesystems ready`
- `ToyOS: processes created`
- `ToyOS: scheduler rounds completed`
- `ToyOS: kernel services online`

Pass condition:

- all markers appear in order

Fail condition:

- panic, reset loop, or missing marker sequence

### A2 Filesystem seed content

Expected content surface:

- TinyFS: `etc/motd`, `usr/readme.txt`, `var/log/boot.log`
- RAMFS: `proc/meminfo`, `proc/drivers`, `proc/ring3`, `tmp/session`

Pass condition:

- kernel reports filesystem initialization without panic
- user-level listing and read tests can observe expected names and sample contents

### A3 User probe syscall path

Expected console and log markers:

- `[user-probe] checking VFS syscalls`
- `ramfs-files=`
- `tinyfs-files=`
- `tinyfs[0]=`
- `motd=`
- `drivers=`
- `motd-repeat-match=1`
- `missing-read-status=1`
- `empty-path-status=1`
- `invalid-syscall-status=4294967295`
- `ToyOS: user probe complete`

Pass condition:

- user probe prints counts
- at least one TinyFS file name is returned
- `etc/motd` and `proc/drivers` are readable from ring3
- repeated reads of `etc/motd` remain stable
- missing-path and empty-path reads fail cleanly
- an invalid syscall returns the documented invalid status without destabilizing execution
- log marker reaches `proc/syscall.last` path or debug stream

Fail condition:

- syscall handler returns invalid values for known files
- user process exits before emitting probe completion marker

### A4 User shell command surface

Commands that must remain supported:

- `help`
- `pid`
- `ticks`
- `mem`
- `pages`
- `ls`
- `cat <path>`
- `exit`

Manual interaction pass condition:

- shell prompt appears as `shell> `
- each command produces a sane response
- `ls` prints both `ramfs` and `tinyfs` sections
- `cat etc/motd` returns TinyFS content
- `cat proc/drivers` returns RAMFS content
- `cat missing/file.txt` reports a not-found condition without destabilizing the shell path
- `exit` terminates the shell process cleanly

Automation note:

- scripted shell probe now covers `help`, `ls`, repeated `cat` on known paths, and missing-path handling
- true keyboard-input behavior is still only partially automated and should remain under manual spot checks

### A5 Scheduler visibility and process report

Expected report surface:

- known slots count
- ring3 prepared count
- ring3 active flag
- ticks
- current index
- per-process rows including pid, name, privilege, runs, slice, kernel stack, and user stack when applicable

Pass condition:

- process report renders without fault
- `user-probe` and `user-shell` appear as user processes
- kernel maintenance process appears as kernel process

### A6 Interrupt and syscall smoke

Expected marker:

- `Triggering a software interrupt test...`

Pass condition:

- kernel continues past the interrupt test and prints `ToyOS kernel services are online.`

### A7 Memory visibility smoke

Expected report fields:

- heap bytes used
- pages used
- pages total
- paging enabled
- mapped mb

Pass condition:

- report prints without panic
- default boot still reports paging disabled
- mapped megabytes still matches current paging implementation metadata

## Stage B: guarded experimental regressions

These checks are not part of the default stable contract yet. They should only run behind explicit debug or test switches.

### B1 Paging smoke path

Required markers:

- pre-enable paging marker
- post-enable paging marker
- failure marker or explicit panic path

Pass condition:

- default boot remains unchanged
- gated test boot reaches post-enable marker

Known blocker:

- ring3 return path is not yet unified for stable paged execution

### B2 Invalid syscall and pointer-hardening tests

Current status:

- invalid syscall number is now probed from user mode and should return the documented invalid status
- pointer hardening still stops at the shared staging stub

Future checks:

- invalid syscall number returns error without corrupting scheduler state
- null pointers return failure
- empty-path and missing-path reads remain bounded negative cases
- unmapped or kernel-only user pointers are rejected once real address validation exists

### B3 Filesystem concurrency pressure

Current status:

- VFS uses a spinlock and is suitable for simple same-core serialization tests
- a bounded kernel-side stress probe now verifies write-read-reread sanity for RAMFS and TinyFS
- alternating kernel writers now verify that multiple process-owned files stay readable across scheduler interleaving
- a user-mode mixed probe now reads kernel-written files through the syscall path after interleaved writer activity

Future checks:

- multiple kernel/user writers do not corrupt file listings
- repeated reads during writes preserve file-system integrity
- user-mode readers can still observe kernel-written files through the syscall boundary after interleaving
- TinyFS directory and data block state remain mountable after stress

### B4 Scheduler preemption and process-state expansion

Future checks:

- timer-driven preemption rotates runnable tasks without explicit yield
- blocked tasks do not consume runtime
- priority materially affects dispatch order
- exited tasks remain visible for reporting until cleanup policy runs

## Recommended execution modes

### Mode 1: static review

Use when no emulator is available.

Checks:

- verify stable boot still keeps `paging_initialize()` disabled
- verify user shell command table still includes `ls` and `cat`
- verify syscall switch still includes filesystem count, name, and read calls
- verify VFS still exports readable seed content paths used by user probe

### Mode 2: QEMU smoke

Use when the kernel image can be booted under QEMU or equivalent emulator.

Checks:

- collect debug port markers
- verify stable boot sequence
- verify user probe output
- manually exercise shell commands if keyboard input path is available

### Mode 3: guarded experiment

Use when a branch explicitly introduces paging smoke or scheduler experimentation.

Checks:

- run Stage B items only behind explicit branch-specific flags
- do not reinterpret experimental success as stable-path promotion

## Minimum acceptance set for current branches

For a ToyOS branch to claim regression safety today, it should satisfy:

1. Stage A1 boot and subsystem bring-up
2. Stage A2 filesystem seed content
3. Stage A3 user probe syscall path
4. Stage A5 scheduler visibility and process report
5. Stage A6 interrupt and syscall smoke
6. Stage A7 memory visibility smoke

Manual shell checks from A4 are still recommended for raw keyboard behavior, but command-surface automation now exists through the scripted shell probe.

## Known gaps

These are not regressions if absent today, but they must be called out:

- no automated shell-input harness yet
- no stable paged ring3 regression yet
- no invalid-pointer enforcement beyond null checks
- no concurrency stress harness for VFS yet
- no true timer-preemptive scheduler regression yet
- no ELF-loader regression surface yet

## Next recommended test artifacts

1. `generic_qemu_smoke` update that explicitly checks user-probe completion and stable marker order
2. shell-scripted interaction plan for `help`, `ls`, and `cat`
3. bounded filesystem stress probe for RAMFS/TinyFS write-read-reread sanity
4. alternating multi-writer verification for RAMFS/TinyFS stability across scheduler interleaving
5. invalid-syscall probe once syscall error contract is expanded
6. paging smoke checklist for Stage 1 gated experiments
