ToyOS P1 task: deepen the security module by turning one sub-area into a clear demo highlight.

Preferred direction:
- Advance the existing TLS path into a clearer end-to-end handshake demonstration.

Alternative only if TLS is blocked:
- Implement a simple AES capability with a focused kernel/user demo.

Scope:
- Choose one highlight and make it demonstrably real inside ToyOS.
- Prefer extending existing security code over starting a disconnected subsystem.

Expected delivery:
- Source changes under D:\codex\generated\toy-os-demo\security and any required kernel/syscall integration.
- A runnable or inspectable demo path proving the chosen security feature works.
- Refreshed evidence and a short machine-readable or markdown note explaining the chosen design.

Acceptance:
- The chosen feature is demonstrably executed, not just statically present.
- Failure paths are handled deterministically.
- The implementation is small enough to audit but substantial enough to count as a showcase feature.

Constraints:
- Prefer TLS handshake advancement first because security/tls already exists in the tree.
- Do not inflate scope into full production crypto coverage.
