ARCH := i686-elf
AS := nasm
CC := $(shell command -v $(ARCH)-gcc 2>/dev/null || command -v gcc 2>/dev/null)
LD := $(shell command -v $(ARCH)-ld 2>/dev/null || command -v ld 2>/dev/null)
PYTHON := $(shell command -v python3 2>/dev/null || command -v python 2>/dev/null || printf '%s' ../../tools/python311-embed/python.exe)
GRUB_MKRESCUE := $(shell command -v grub-mkrescue 2>/dev/null)
QEMU := $(shell command -v qemu-system-i386 2>/dev/null)
TOYOS_EXPERIMENTAL_PAGING_STAGE1 ?= 0
CFLAGS := -std=gnu99 -ffreestanding -O2 -Wall -Wextra -Iinclude -DTOYOS_EXPERIMENTAL_PAGING_STAGE1=$(TOYOS_EXPERIMENTAL_PAGING_STAGE1)
LDFLAGS := -T linker.ld -nostdlib

ifeq ($(findstring i686-elf,$(CC)),)
  CFLAGS += -m32
endif
ifeq ($(findstring i686-elf,$(LD)),)
  LDFLAGS += -m elf_i386
endif

BUILD := build
BUILD_STAMP := $(BUILD)/.dir
KERNEL := $(BUILD)/kernel.bin
ISO_DIR := $(BUILD)/iso
ISO_IMAGE := $(BUILD)/toyos.iso
ASM_SOURCES := boot.asm src/isr_stub.asm
C_SOURCES := kernel.c src/terminal.c src/idt.c src/memory.c src/paging.c src/scheduler.c src/vfs.c src/timer.c src/keyboard.c src/block_device.c src/gdt.c src/panic.c src/syscall.c security/tls/tls.c security/tls/tls_handshake.c security/tls/tls_record.c security/tls/tls_crypto.c security/tls/tls_session.c security/rpc/secure_rpc.c security/keystore/keystore.c security/monitor/security_monitor.c
ASM_OBJECTS := $(patsubst %.asm,$(BUILD)/%.o,$(ASM_SOURCES))
C_OBJECTS := $(patsubst %.c,$(BUILD)/%.o,$(C_SOURCES))
OBJECTS := $(ASM_OBJECTS) $(C_OBJECTS)

.PHONY: all build iso run run-iso qemu-smoke test real-hardware clean \
	kernel-host iso-host run-host run-iso-host qemu-smoke-host test-host real-hardware-host clean-host

all: build

build:
	$(PYTHON) tools/system_toolchain.py build

$(BUILD_STAMP):
	mkdir -p $(BUILD)
	@touch $(BUILD_STAMP)

$(BUILD)/%.o: %.asm | $(BUILD_STAMP)
	mkdir -p $(dir $@)
	$(AS) -f elf32 $< -o $@

$(BUILD)/%.o: %.c | $(BUILD_STAMP)
	mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(KERNEL): $(OBJECTS) linker.ld
	$(LD) $(LDFLAGS) -o $@ $(OBJECTS)

kernel-host: $(KERNEL)

$(ISO_DIR)/boot/grub/grub.cfg: grub/grub.cfg | $(BUILD_STAMP)
	mkdir -p $(ISO_DIR)/boot/grub
	cp $< $@

$(ISO_DIR)/boot/kernel.bin: $(KERNEL) | $(BUILD_STAMP)
	mkdir -p $(ISO_DIR)/boot
	cp $(KERNEL) $@

iso:
	$(PYTHON) tools/system_toolchain.py iso

iso-host: $(ISO_DIR)/boot/kernel.bin $(ISO_DIR)/boot/grub/grub.cfg
	@if [ -z "$(GRUB_MKRESCUE)" ]; then echo "grub-mkrescue is required for iso target"; exit 1; fi
	$(GRUB_MKRESCUE) -o $(ISO_IMAGE) $(ISO_DIR)

run:
	$(PYTHON) tools/system_toolchain.py run

run-host: $(KERNEL)
	@if [ -z "$(QEMU)" ]; then echo "qemu-system-i386 is required for run target"; exit 1; fi
	$(QEMU) -kernel $(KERNEL)

run-iso:
	$(PYTHON) tools/system_toolchain.py run-iso

run-iso-host: iso-host
	@if [ -z "$(QEMU)" ]; then echo "qemu-system-i386 is required for run-iso target"; exit 1; fi
	$(QEMU) -cdrom $(ISO_IMAGE)

qemu-smoke:
	$(PYTHON) tools/system_toolchain.py qemu-smoke

qemu-smoke-host:
	@if [ -z "$(QEMU)" ]; then echo "qemu-system-i386 is required for qemu-smoke target"; exit 1; fi
	$(PYTHON) ../../orchestrator-mvp/tools/build_toy_os.py --target .
	$(PYTHON) ../../orchestrator-mvp/tools/generic_test_runner.py --spec tools/generic_qemu_smoke.json

test:
	$(PYTHON) tools/system_toolchain.py test

test-host:
	$(PYTHON) ../../orchestrator-mvp/tools/build_toy_os.py --target .
	$(PYTHON) ../../orchestrator-mvp/tools/score_toy_os.py --target .

real-hardware:
	$(PYTHON) tools/system_toolchain.py real-hardware

real-hardware-host: iso-host
	@echo "ISO ready: $(ISO_IMAGE)"
	@echo "Write it to a USB drive with a tool such as Rufus or balenaEtcher, then boot the machine from that USB device."

clean:
	$(PYTHON) tools/system_toolchain.py clean

clean-host:
	rm -rf $(BUILD)
	rm -f build-report.json
