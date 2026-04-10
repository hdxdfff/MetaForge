ToyOS P1 task: add a simple ELF loader so ToyOS can run externally built user programs.

Scope:
- Implement a minimal ELF loader for a bounded executable subset.
- Load an external program image into a user process address space.
- Reuse the scheduler/process launch path instead of inventing a separate execution model.

Expected delivery:
- Source changes under D:\codex\generated\toy-os-demo for program loading and process setup.
- At least one minimal external test program and a documented loading path.
- Refreshed evidence showing the loader path was exercised.

Acceptance:
- A supported ELF user binary can be loaded and executed.
- The loader rejects unsupported or malformed binaries safely.
- The loaded program runs in user mode rather than as a kernel stub.

Constraints:
- Keep the first version narrow and explicit about the supported ELF subset.
- Avoid claiming general ELF compatibility if the implementation only supports a minimal profile.
