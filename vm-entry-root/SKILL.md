---
name: "vm-access-mirror"
description: "Local mirror of the established VMware VM access wrappers and recipes for D:\\codex. Use as the working copy when the VM toolchain needs inspection or repair."
---

# VM Access Mirror

## Purpose
- Keep a local mirror of the VM entry scripts so wrapper fixes can be made without touching the VM source copy first.
- Treat `E:\codex` as the source-of-truth runtime wrapper tree and this folder as the editable working copy.

## Contents
- `vmctl.cmd` / `vmctl.ps1`
- `vm-common.ps1`
- `vm-check.*`, `vm-ssh.*`, `vm-run.*`
- `vm-put.*`, `vm-get.*`, `vm-plink.*`, `vm-pandoc-pdf-zh.*`
- `VM_AGENT_ACCESS.md`

## Use
- Inspect wrapper behavior here before changing runtime code in the VM tree.
- Keep any fixes bounded to path resolution, temporary directories, and command routing.
- Validate wrapper changes by re-running the cheapest available VM health check.

## Notes
- This mirror does not replace the VM tree automatically.
- When a fix is proven here, sync it back to the authoritative VM wrapper location.
