# Capability Deepen Evidence (Tool Routing Hardening)

- Automation ID: capability-deepen-2
- Timestamp (UTC): $iso
- Focus: tool integration routing safety

## Improvement

Hardened tool routing keyword matching in 	ools/tool_registry.py by replacing naive substring matching with boundary-aware matching and flexible phrase whitespace matching. This prevents false positives like git matching inside digital while preserving phrase matches such as unit    test.

## Validation

1. py_compile passed for changed files.
2. Direct route smoke assertions passed:
   - digital signature ... selected sign_verify (not git_status)
   - unit    test ... selected pytest_run
3. Targeted pytest invocation was blocked by a broken local venv interpreter path.

## Changed Files

- D:/codex/orchestrator-mvp/tools/tool_registry.py
- D:/codex/orchestrator-mvp/tests/test_tool_registry.py

## Residual Risk

- Matching remains keyword-driven; semantic-only requests still depend on keywords.
- Full test-suite confidence remains limited until the venv interpreter path is repaired.
