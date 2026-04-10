# ToyOS Paging Stage 0 Branch Goal

Scope: only `D:\codex\generated\toy-os-demo`

Do not modify:

- `D:\codex\orchestrator-mvp\app`
- `D:\codex\orchestrator-mvp\runtime`
- `D:\codex\orchestrator-mvp\tools`
- MetaForge OS control or routing logic

## Goal

Document and validate the minimum safe path for enabling paging in ToyOS without breaking the current stable boot and ring3 teaching path.

Stage 0 is documentation plus guarded test planning.
It is not the stage that permanently enables paging in the default boot path.

## Current kernel facts

Observed from the current ToyOS codebase:

- `paging_initialize()` exists and enables CR3 plus CR0.PG in [`paging.c`](D:\codex\generated\toy-os-demo\src\paging.c)
- it currently builds two identity-mapped page tables, which maps 8 MiB total
- the current mapping marks both directory and table entries as `PAGE_USER`
- paging is still disabled in the stable path in [`kernel.c`](D:\codex\generated\toy-os-demo\kernel.c)
- the stable kernel comment already says paging is held back until full ring3 context restore is implemented
- the scheduler currently tracks ring3 readiness and user stacks, but not a per-process page directory
- syscall return and cooperative user switching already rely on a special return path that is not yet unified with timer-preemption needs

## Stage 0 objectives

1. Make the current paging assumptions explicit.
2. Define the exact boot-time safety gate for a paging smoke path.
3. Record the ring3 return constraints that block unconditional enablement.
4. Prepare the next stage so paging can be tested without silently changing the stable kernel contract.

## Stage 0 deliverables

1. Paging layout note

- current page directory address source
- number of identity tables
- mapped memory size
- current user/kernel flags on PDE/PTE entries

2. Boot gating note

- where paging can be toggled for smoke testing
- what debug markers must appear before and after paging enablement
- what panic or fallback behavior is required if the system cannot safely continue

3. Ring3 constraint note

- why the current user return path is still a blocker
- what must be true before paging becomes part of the stable default boot

4. Validation note

- exact QEMU/debugcon checks required before claiming Stage 0 complete

## Current layout assumptions

Based on the current implementation:

- page size: 4 KiB
- page-directory entries: 1024
- page-table entries: 1024
- identity tables: 2
- mapped size: 8 MiB
- CR3 is loaded with the static page directory
- CR0.PG is set immediately after CR3 load

## Stage 0 risks

1. User flag overexposure

Current PDE/PTE entries are marked with `PAGE_USER`.
For Stage 0 this is acceptable only as a documented teaching simplification, not as the final protection model.

2. Return-path fragility

The kernel already notes that full ring3 context restore is incomplete.
If paging is enabled before the interrupt/syscall/user return path is unified, a fault may occur after otherwise successful early boot.

3. Hidden pointer-validation gap

Current syscalls only do null checks for read-buffer arguments.
Paging will make this unsafe unless later stages add address validation.

4. No per-process address-space ownership

The scheduler has no field for page-directory or address-space metadata yet.
Stage 0 must avoid implying that per-process isolation already exists.

## Non-goals

Stage 0 does not:

- enable paging in the default stable boot path
- introduce per-process page directories
- implement copy-on-write, demand paging, or swapping
- solve unified timer-preemptive ring3 resume
- finalize user-pointer validation

## Proposed Stage 0 implementation boundary

Allowed:

- comments and docs
- a gated smoke path behind an explicit debug/test switch
- extra debug markers around paging enablement
- QEMU smoke spec updates

Not yet allowed:

- unconditional `paging_initialize()` in the stable boot path
- scheduler ABI changes for address spaces
- broad syscall ABI claims about protected user memory

## Acceptance criteria

Stage 0 is complete only if all of the following are true:

1. The current paging layout is documented in-repo.
2. The default boot path remains unchanged and stable.
3. A paging smoke path is defined as gated and non-default.
4. Required debug markers and failure expectations are written down.
5. Ring3 return limitations are explicitly recorded as the blocker for Stage 1 promotion.

## Validation

Required validation for Stage 0 completion:

1. Static verification

- confirm `paging_initialize()` remains gated or disabled in the stable path
- confirm mapped size and flags match the current implementation

2. QEMU/debugcon planning

- define pre-enable marker
- define post-enable marker
- define failure marker or panic expectation

3. Residual limitation note

- explicitly state that this branch goal does not prove stable paged ring3 execution

## Recommended next step after Stage 0

Move to Stage 1 only after introducing:

- a gated paging smoke path
- explicit debug markers around CR3/CR0.PG enablement
- a documented fallback or panic-safe stop condition
- a clearer plan for unifying syscall return and future timer-preemptive return
