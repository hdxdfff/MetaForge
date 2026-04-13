# ToyOS ELF Format Note

Scope: only `D:\codex\generated\toy-os-demo`

Do not modify:

- `D:\codex\orchestrator-mvp\app`
- `D:\codex\orchestrator-mvp\runtime`
- `D:\codex\orchestrator-mvp\tools`
- MetaForge OS control or routing logic

## Goal

Define the first accepted ELF subset for ToyOS so that later loader work has a fixed input contract.

This note is intentionally narrow.
It defines what a first ToyOS-loadable executable should look like before the kernel claims to load arbitrary binaries.

## Current project reality

Observed from the current repo:

- ToyOS currently builds one kernel image, not separate user-program artifacts
- user processes are still kernel-linked C functions
- paging is not enabled in the default stable boot path
- there is no per-process address-space object yet
- there is no filesystem-backed executable loading path yet

Because of that, the first ELF contract must be strict and small.

## Accepted ELF target for the first ToyOS loader

The first ToyOS loader should accept only:

- ELF32
- little-endian
- x86 / i386 machine type
- executable image, not relocatable object
- statically laid out loadable segments
- no dynamic linking
- no interpreter segment requirement

In practical terms, the accepted image should be a teaching binary that the kernel can validate and place into memory without needing a dynamic runtime.

## Header expectations

The first loader should require all of the following:

- valid ELF magic
- class = 32-bit
- data = little-endian
- version = current
- machine = i386
- executable type or a narrowly allowed static form defined by ToyOS
- non-zero entry address
- program-header table present
- at least one loadable segment

The first loader should reject if any of these checks fail.

## Program-header expectations

The first loader should only support loadable segments that are easy to map into the teaching kernel model.

Recommended accepted subset:

- `PT_LOAD` segments only
- segment file size less than or equal to memory size
- segment alignment is page-friendly or explicitly documented as loader-rounded
- no overlapping load ranges
- no segment range that exceeds ToyOS teaching memory limits

The first loader should reject or ignore any unsupported segment type explicitly.

For the first milestone, rejecting unsupported segment layouts is better than silently approximating them.

## Memory layout expectations

The first ToyOS ELF path should define a teaching layout with these concepts:

- image base
- image limit
- code and data pages loaded from `PT_LOAD` segments
- one initial user stack region
- one entry address inside the accepted image range

The format contract should require:

- entry address lies inside a loadable executable image range
- segment virtual addresses form a sane non-overlapping image interval
- total required pages fit in available ToyOS page allocator limits

This is still not a full virtual-memory design.
It is only enough to keep the first image loader deterministic.

## What the first ELF contract should reject

The initial loader should reject at least these cases:

- wrong ELF magic
- wrong class
- wrong endianness
- wrong machine type
- zero entry point
- missing program headers
- zero loadable segments
- loadable segment with `filesz > memsz`
- overlapping segment ranges
- segment range that would exceed available memory budget
- image requiring unsupported dynamic or interpreter behavior

## Recommended ToyOS-specific simplifications

To keep the first loader tractable, ToyOS should explicitly allow these simplifications:

1. Single-user-image teaching binaries only.
2. Static linking only.
3. No relocation processing in the first milestone.
4. No shared-library or runtime interpreter support.
5. No promise yet that ELF virtual addresses correspond to isolated per-process address spaces.

These simplifications are not flaws at this stage; they are scope control.

## Suggested file placement contract

For the first runnable milestone, user images should come from a simple in-repo teaching path, for example:

- a TinyFS file such as `bin/hello.elf`
- or a RAMFS-injected staging file during early experiments

Preferred first stable direction:

- TinyFS-backed image file, because it aligns with the existing persistent teaching filesystem layer

## Suggested build evolution

The current Makefile does not yet emit user ELF binaries.

Recommended future build additions:

- a small user-program source directory
- a separate link target for a flat ELF32 user image
- a packaging step that places the image into TinyFS seed content or an equivalent staging path

This note does not require that build work yet.
It only records that later loader work should target a real ELF artifact, not an ad hoc byte blob.

## Recommended loader-visible metadata

When a future loader validates an ELF image, it should produce at least:

- image name
- entry address
- image base
- image limit
- image page count
- loadable segment count
- validation result

That metadata should be enough to populate the proposed `process_image_launch_t` handoff.

## Suggested debug markers

For a future loader implementation, require markers such as:

- `ToyOS: elf validate begin`
- `ToyOS: elf header accepted`
- `ToyOS: elf segments accepted`
- `ToyOS: elf image prepared`

Failure markers:

- `ToyOS: elf bad magic`
- `ToyOS: elf unsupported class`
- `ToyOS: elf unsupported machine`
- `ToyOS: elf bad segment layout`
- `ToyOS: elf image too large`

## Non-goals of this format note

This note does not define:

- full ABI for user arguments
- relocation algorithm
- dynamic loader behavior
- shared objects
- symbol resolution
- per-process page-directory mapping rules
- syscall ABI of loaded programs beyond current ToyOS syscall set

Those belong to later stages.

## Acceptance criteria

This ELF format note is complete only if all of the following are true:

1. It defines a small accepted ELF subset.
2. It lists the first mandatory validation gates.
3. It states what must be rejected, not just what is accepted.
4. It stays consistent with current ToyOS memory and scheduler limits.
5. It does not overclaim isolated virtual-memory semantics that do not exist yet.

## Recommended next step

After this note, the strongest next ToyOS step is either:

1. a real scheduler metadata implementation branch based on [`TOYOS_IMAGE_PROCESS_PATCH_PROPOSAL.md`](D:\codex\generated\toy-os-demo\TOYOS_IMAGE_PROCESS_PATCH_PROPOSAL.md)
2. a minimal kernel-side ELF validation stub that only parses and reports header or segment acceptance
3. a writable-file syscall patch proposal so userland capability continues to grow alongside loader planning
