ToyOS P0 task: extend TinyFS beyond the current single-block flat-file design.

Scope:
- Add multi-block file support.
- Add directory hierarchy support.
- Add a simple crash-recovery mechanism suitable for this filesystem scale.
- Keep the implementation understandable and auditable; avoid overdesign.

Expected delivery:
- Source changes under D:\codex\generated\toy-os-demo for TinyFS/VFS and any supporting storage code.
- Updated test or probe paths that demonstrate nested paths and files larger than one block.
- Refreshed evidence outputs if build/test coverage exists.

Acceptance:
- TinyFS can store and read files larger than one block.
- Nested directory paths are represented and accessible.
- On a simulated interrupted write or mount cycle, the filesystem can recover to a consistent readable state.
- Existing simple file operations still work.

Constraints:
- Keep on-disk format changes explicit and documented in code/comments when needed.
- Reuse the current ramdisk/block-device model instead of introducing unrelated infrastructure.
