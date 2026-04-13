# ToyOS Factory Branch Goals

Scope: only `D:\codex\generated\toy-os-demo`

Do not modify:
- `D:\codex\orchestrator-mvp\app`
- `D:\codex\orchestrator-mvp\runtime`
- `D:\codex\orchestrator-mvp\tools`
- factory control layer or meta-factory mainline

## Operator intent

Continue ToyOS mainline development from the ToyOS branch conversation.
Use the meta-factory only as auxiliary execution capacity.
If a task drifts into platform or control-layer changes, stop implementation and emit only a patch proposal or branch goal.

## Priority lanes

### Lane A: Paging bring-up

Goal:
- enable paging incrementally without breaking the current stable boot path

Stages:
1. Stage 0: document current page-table layout, CR0/CR3 assumptions, and ring3 return constraints
2. Stage 1: add a gated paging smoke path with explicit debug markers and panic-safe fallback
3. Stage 2: prepare for per-process address-space evolution and kernel/user mapping split

Current status:
- `paging_initialize()` commented in kernel.c:523, kept disabled until full ring3 context restore

Immediate actions:
1. Uncomment paging_initialize() in a controlled test path with fallback mechanism
2. Add paging-enabled boot test to QEMU smoke suite
3. Document address space layout assumptions for future per-process page tables

Deliverables:
- branch goal
- risk list  
- minimal safe patch or patch proposal
- validation steps for QEMU/debugcon

### Lane B: Scheduler evolution

Goal:
- move from cooperative dispatch toward true preemptive multitasking

Required analysis:
- timer interrupt preemption points
- full kernel/user register save-restore needs
- ring3 resume path
- process state expansion beyond READY/RUNNING/BLOCKED/EXITED
- priority handling design and starvation notes

Current issues:
1. User-mode return path special case: syscalls use `scheduler_ring3_return_requested` flag and `ret` instead of standard `iretd` (isr_stub.asm:60-64)
2. This custom mechanism works for cooperative yield/exit but complicates future preemptive context switching
3. Need unified interrupt/exception return path that works for both syscall returns and timer preemption

Immediate actions:
1. Document current return mechanism and its limitations
2. Design unified context save/restore for both syscall and timer interrupt paths
3. Test gradual migration from cooperative to preemptive with controlled fallback

Deliverables:
- branch goal
- context-switch design note
- minimal safe patch or patch proposal
- regression checklist

### Lane C: Syscall expansion

Goal:
- extend ToyOS syscalls with the next minimal OS-facing interfaces

Priority:
1. file read/write primitives
2. illegal syscall handling and error reporting
3. memory mapping interface sketch

Current issues:
1. Syscall parameter validation: RAMFS_READ/TINYFS_READ (syscall.c:113-121) only check for null pointers
2. No address space validation for user buffer pointers (critical for paging enablement)
3. Need robust pointer validation before enabling paging to prevent security issues

Immediate actions:
1. Add address validation stub that always passes in current non-paged mode
2. Design pointer validation API that can evolve with paging stages
3. Add syscall parameter validation test to QEMU regression suite

Deliverables:
- syscall matrix with parameter validation requirements
- ABI notes including security constraints
- minimal implementation plan or patch proposal

### Lane D: ELF loader roadmap

Goal:
- replace kernel-direct user entry with a staged loader path

Stages:
1. ELF parser and validation
2. segment loading into memory regions
3. user stack and argv scaffold
4. scheduler/user entry integration

Deliverables:
- branch goal
- interface sketch
- dependency list

### Lane E: Test expansion

Goal:
- move beyond boot/smoke into subsystem regression

Required suites:
- filesystem concurrency
- memory pressure
- illegal syscall behavior
- user shell / user probe regression

Current issues:
1. Filesystem concurrency: current spinlock (vfs.c:34) works for single-core but needs enhancement for SMP
2. User shell interaction: backspace handling only reduces line length without visual deletion (kernel.c:340-342)
3. cat command output limited by VGA scrollback, no paging support
4. Terminal interaction lacks proper line editing feedback

Immediate actions:
1. Document VFS locking assumptions and SMP readiness
2. Enhance shell backspace to erase character visually
3. Design terminal paging/scrollback mechanism for long outputs
4. Add filesystem concurrency stress test to QEMU suite

Deliverables:
- test plan including concurrency and UI regression tests
- QEMU/debugcon marker list
- proposed spec additions

### Lane F: Documentation

Goal:
- make ToyOS understandable as a teaching kernel

Required docs:
- kernel boot flow
- GDT/IDT/syscall/scheduler interactions
- memory and VFS interfaces
- user-mode execution path

Deliverables:
- docs outline
- module interface summary

## Factory dispatches created

- `b7b8f7b1313f4f128f974490880f7557`: paging + scheduler lane
- `6005f5fb797a45039fccedc2d2d12be1`: syscall + ELF + test + docs lane

## Acceptance rule

Any worker output must preserve the ToyOS-only boundary. If a proposed change touches platform routing, controller logic, or factory runtime, convert it into a patch proposal instead of implementation.
