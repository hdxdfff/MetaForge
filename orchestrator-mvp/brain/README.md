# Brain Layer

This directory stores the persistent "brain" for the local AI factory.

Principle:

- chat is the operator interface
- controller is the execution bridge
- state is the source of truth
- agents and tools are replaceable workers

Files:

- `system_blueprint.json`: durable architecture and module map
- `brain_prompt.md`: top-brain operating prompt for Codex-first control
- `memory.json`: stable memory and operator rules

These files are meant to survive chat resets and should be loaded before
planning or supervision work.
