---
name: "vm-entry-local"
description: "Local VM entry rooted in D:\\codex. Use D:\\codex\\vm-entry.cmd as the preferred launcher and D:\\codex\\vm-entry-root as the editable wrapper tree."
---

# VM Entry Local

## Purpose
- Provide a D:\codex-owned VM launcher and wrapper tree.
- Keep the local workspace as the preferred control point for VM access.

## Preferred Entry
- `D:\codex\vm-entry.cmd`

## Use
- Prefer the local entry for VM checks, SSH, and guest command execution.
- Keep fixes scoped to `D:\codex\vm-entry-root` first.
- Do not treat `E:\codex` wrappers or keys as runtime defaults.

## Validation
- Run the cheapest check first:
  - `D:\codex\vm-entry.cmd check`
- If SSH is unavailable, treat that as a VM connectivity issue rather than an entry issue once the launcher paths are validated.

## Notes
- `D:\codex\.vm-keys\id_ed25519_host` is the canonical primary SSH key.
- `D:\codex\.vm-keys\id_ed25519_strict` is compatibility fallback only.
