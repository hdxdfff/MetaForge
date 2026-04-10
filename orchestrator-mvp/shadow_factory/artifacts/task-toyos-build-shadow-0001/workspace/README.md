# ToyOS

Security-network scaffolding is now present under include/security.h and security/, with a staged architecture note in TOYOS_SECURITY_NETWORK_ARCHITECTURE.md. It is intentionally compile-safe scaffolding, not a claim of production-ready TLS or Zero Trust networking.

This project is a teaching-oriented x86 kernel scaffold generated and extended by AI Command Console.

## What it contains now

- `boot.asm`: Multiboot header and bootstrap entry.
- `kernel.c`: Main kernel flow that initializes GDT, IDT, syscalls, memory, filesystems, processes, and drivers.
- `src/gdt.c`: Kernel/user segment descriptor setup plus a loaded TSS for kernel stack handoff on privilege transitions.
- `src/idt.c`: Interrupt descriptor table setup, IRQ registration, and syscall gate registration.
- `src/isr_stub.asm`: Interrupt and syscall entry stubs that forward register frames into C.
- `src/syscall.c`: `int 0x80` syscall handler, telemetry hooks, and minimal VFS inspection services for user mode.
- `src/scheduler.c`: Process-oriented round-robin scheduler with time slices, dynamic create/destroy, and per-process kernel/user stack preparation.
- `src/panic.c`: Kernel panic handler.
- `src/vfs.c`: RAMFS plus TinyFS with spinlock-protected filesystem operations.
- `src/terminal.c`: VGA text-mode terminal implementation.
- `src/memory.c`: Simple kernel heap and fixed-size page allocator.
- `src/paging.c`: Teaching-oriented paging scaffold with identity-mapped page tables kept available for later virtual-memory work.
- `src/timer.c`: PIT timer driver and scheduler tick source.
- `src/keyboard.c`: IRQ-driven keyboard input buffer.
- `src/block_device.c`: Memory-backed block device used as a ramdisk layer.
- `grub/grub.cfg`: GRUB boot entry used to produce a bootable ISO for real-machine tests.
- `tools/generic_qemu_smoke.json`: generic regression spec consumed by the shared test runner.

## Current capability level

This is still a kernel prototype, not a production operating system. It now has:

- protected-mode entry through a Multiboot-compatible loader
- kernel and user segment descriptors in the GDT
- a loaded TSS with `esp0` tracking for ring3 to ring0 transitions
- `int 0x80` syscall gate in the IDT with verified user-mode entry and return
- a process-oriented scheduler with dynamic creation and destruction
- a ring3 user-shell path that exercises syscall entry, console output, VFS inspection, and scheduler return
- per-process kernel stack allocation and per-user-process user stack allocation
- time-slice accounting and cooperative yield/exit syscalls
- a kernel panic path for unrecoverable resource failures
- spinlock-protected filesystem operations
- a RAM-backed volatile filesystem and a TinyFS block-backed filesystem layer
- PIT timer initialization and keyboard IRQ buffering
- GRUB ISO packaging for physical-machine boot attempts
- a paging subsystem implemented in code, but left disabled in the default stable boot path until full ring3 context restoration is finished
- reusable automated QEMU regression testing through the shared generic test runner

## Build and boot targets

- `python tools/system_toolchain.py status`: inspect which backend the system will use
- `make` or `python tools/system_toolchain.py build`: build `build/kernel.bin`
- `make run` or `python tools/system_toolchain.py run`: boot the kernel directly; when only the managed backend is available this falls back to headless QEMU
- `make iso` or `python tools/system_toolchain.py iso`: create `build/toyos.iso`
- `make run-iso` or `python tools/system_toolchain.py run-iso`: boot the GRUB ISO
- `make qemu-smoke` or `python tools/system_toolchain.py qemu-smoke`: run repeated VM smoke, soak, and guarded paging-stage1 tests
- `make test` or `python tools/system_toolchain.py test`: refresh build evidence and score reports
- `make real-hardware`: build the ISO through the selected backend, then follow the USB boot checklist below

The operator-facing entrypoints no longer assume you will manually install `nasm`, `gcc`, `ld`, or `qemu-system-i386`.
The system now resolves them in this order:

1. native host tools when they are already available
2. a Docker-managed Debian build/runtime image using the local `debian:13-slim` base when available; if Docker Desktop is installed but the daemon is down, the wrapper will try to start it first

If both backends are unavailable, the wrapper reports the missing system capability instead of pushing raw toolchain setup back onto the operator.

## Automated testing

The project now exposes a generic test-spec based workflow:

- shared runner: [generic_test_runner.py](D:\codex\orchestrator-mvp\tools\generic_test_runner.py)
- ToyOS suite spec: [generic_qemu_smoke.json](D:\codex\generated\toy-os-demo\tools\generic_qemu_smoke.json)
- generated report: `build/generic-qemu-smoke-report.json`

The current VM regression suite includes:

- `qemu_boot_smoke`: repeated short boot checks with ordered startup markers
- `qemu_boot_soak`: longer VM uptime checks to catch early runtime panics after boot
- `qemu_boot_paging_stage1`: gated paging smoke that proves CR3/CR0.PG enablement without promoting paging to the stable default path
- `qemu_user_probe_assertions`: explicit ring3 VFS, repeat-read, missing-path, empty-path, and invalid-syscall assertions driven by the startup user probe
- `qemu_shell_probe_assertions`: scripted shell command assertions for `help`, `ls`, repeated `cat`, and missing-path handling
- `qemu_filesystem_stress_assertions`: bounded RAMFS/TinyFS write-read stress markers for persistence sanity
- `qemu_filesystem_multiwriter_assertions`: alternating multi-process writer verification for RAMFS/TinyFS stability
- `qemu_filesystem_mixed_assertions`: user-mode syscall reads over kernel-written RAMFS/TinyFS files

The latest verified run reached:

- `qemu_boot_smoke`: `5/5 passed`
- `qemu_boot_soak`: `3/3 passed`
- verified ring3 entry, syscall usage, scheduler return, and stable QEMU boot/soak behavior on the default boot path

This means repeated boot and short-run checks can be delegated to the local coding assistant or other cheap workers instead of requiring premium-model supervision on every round.

## Implemented subsystems

### User-mode and syscall scaffolding

- the GDT includes ring 0 and ring 3 code/data descriptors
- the kernel now loads a TSS descriptor and maintains a dedicated `esp0` stack top
- the syscall layer currently supports log write, yield, exit, PID query, runtime counters, and read-only VFS inspection
- scheduler entries now model processes with kernel/user privilege metadata and prepared stacks

### Process scheduler

- fixed process slots with dynamic create/destroy semantics
- round-robin dispatch with per-process time slices
- timer ticks age the current process slice
- process exit paths are explicit rather than implicit task disappearance
- user processes now launch through a real `iret`-based ring3 handoff and return via syscall exit

### User shell and VFS inspection

- the ring3 shell now supports `ls` and `cat <path>` across RAMFS and TinyFS
- a startup `user-probe` process automatically verifies user-mode VFS syscalls and emits a stable debug marker for QEMU regression runs
- user mode can enumerate file names and read file contents without touching the host platform layer

### Filesystem concurrency

- `RAMFS` remains the volatile runtime filesystem for `proc` and `tmp`
- `TinyFS` remains the block-backed teaching filesystem on the ramdisk
- a spinlock protects filesystem metadata and block operations from concurrent corruption

### Error handling

- heap, page, filesystem, stack, and process creation failures are checked in the kernel boot path
- unrecoverable failures trigger a visible kernel panic instead of silently continuing

## Physical machine status

Physical-machine boot has not been validated by me in this environment.

What is ready now:

- the kernel exposes a Multiboot header
- GRUB ISO packaging is wired into the Makefile
- the project can produce a bootable ISO once `grub-mkrescue` is available
- QEMU smoke and short-run soak tests can be run repeatedly and summarized automatically

What is still not confirmed:

- BIOS versus UEFI differences on your hardware
- GPU/text-mode behavior on your exact machine
- interrupt-controller behavior on bare metal
- whether direct Multiboot loading is enough for your firmware chain
- long-duration runtime stability beyond the current short soak window

That means this prototype is verified for `WSL + QEMU + repeated regression tests`, and partially prepared for `GRUB/real hardware`, but not yet proven on arbitrary bare-metal hardware.

## Real hardware checklist

1. Run `python tools/system_toolchain.py status` and make sure the `iso` backend is available.
2. Run `make iso` inside the project.
3. Write `build/toyos.iso` to a USB drive with Rufus or balenaEtcher.
4. Boot the target machine from the USB drive.
5. If boot fails, note whether GRUB loads, whether the kernel banner appears, and whether the machine resets, hangs, or panics.
## Remaining gaps before it resembles a stronger thesis-grade OS prototype

1. Replace the current one-shot ring3 launch path with fully saved-stack preemptive context switching.
2. Add paging with real page tables and virtual memory regions.
3. Extend TinyFS beyond fixed one-block files into a real inode/block allocator.
4. Add ELF loading and a basic shell/userland loader.
5. Broaden automated runtime tests beyond boot and short soak verification into filesystem and syscall regression suites.










