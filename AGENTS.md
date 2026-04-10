# D:\codex Agent Guide

This workspace is an operator console for MetaForge OS, OpenCode, and local agent experimentation.

## Mission

- Keep the workspace usable as a control plane, not just a scratch repo.
- Prefer repeatable controller-backed workflows over ad hoc exploration.
- Treat every mutating task as a dispatch with a target workspace, validation path, and return artifact.

## First actions

Before changing code or state, run the cheapest relevant status checks:

```powershell
D:\codex\factoryctl.cmd daemon-status
D:\codex\factoryctl.cmd control-layer-status
D:\codex\factoryctl.cmd engineering-os-status
D:\codex\factoryctl.cmd lab-status
```

If the task concerns system quality or regressions, also run:

```powershell
D:\codex\factoryctl.cmd autonomy-score
```

## Mutation contract

- Prefer `D:\codex\factoryctl.cmd` and `D:\codex\opencode-control.ps1` over manual JSON editing.
- Open a controller session before mutating orchestrated state.
- Keep OpenCode-facing changes focused on wrappers, prompts, operator docs, workflows, and validation paths unless backend changes are explicitly requested.
- Do not modify runtime internals only to make a task appear complete.
- Do not claim delivery until the requested artifact exists in the target workspace.
- Every code or documentation mutation must leave behind two backups: a local snapshot under `D:\codex\backups\backup_<timestamp>` and a GitHub push on the working branch.
- Use `D:\codex\backup-and-publish.cmd` or `D:\codex\tools\workspace_backup.py` to create the local snapshot and publish the matching Git commit.
- Do not consider a mutation complete until the snapshot manifest exists and the Git push succeeds.

## Workspace layout

- `D:\codex\orchestrator-mvp`: controller and runtime logic.
- `D:\codex\knowledge`: durable machine-readable project memory.
- `D:\codex\goals`: active and completed goal state.
- `D:\codex\generated`: generated deliverables. ToyOS artifacts must resolve under `D:\codex\generated\toy-os-demo`.
- `D:\codex\tools`: local helper tools, portable runtimes, and discovery scripts.
- `D:\codex\skills`: local workflow playbooks for repeated engineering tasks.
- `D:\codex\workflows`: shared execution and validation templates.

## Execution rules

- Start with repository or subsystem orientation before changing files.
- Prefer cheap-first validation. Escalate cost only when the cheaper check fails or cannot answer the risk.
- When `rg` is unavailable, use PowerShell alternatives instead of blocking.
- Use existing embedded runtimes from `D:\codex\tools` before assuming a global dependency exists.
- Record reusable findings in `D:\codex\knowledge` when the task reveals a recurring bug or validation pattern.

## VM access policy

- Treat the VM as the primary execution root and the Windows host as a control plane plus cached state surface.
- Use `D:\codex\vm-entry.cmd` as the only supported VM entrypoint for command execution and file transfer.
- Use `D:\codex\factoryctl.cmd` for orchestrator-facing workflows such as status, inbox, report, dispatch, and sync.
- Treat `D:\codex\.vm-keys\id_ed25519_host` as the canonical primary SSH key.
- Treat `D:\codex\.vm-keys\id_ed25519_strict` as compatibility fallback only.
- Allowed VM entry commands are:
  `D:\codex\vm-entry.cmd run ...`
  `D:\codex\vm-entry.cmd ssh ...`
  `D:\codex\vm-entry.cmd put <host-path> <guest-path>`
  `D:\codex\vm-entry.cmd get <guest-path> <host-path>`
- Do not call `vmrun.exe` directly.
- Do not treat VMware Tools or Guest Ops as required for normal task execution.
- Do not handcraft SSH or SCP parameters when `D:\codex\vm-entry.cmd` already covers the action.
- Do not rely on legacy `E:\codex\...` wrappers when the same capability exists under `D:\codex\...`.
- Do not treat `E:\codex\.vm-keys` as an active runtime key source.
- If host-side status is degraded but `vm_ssh_primary` is healthy, continue working through the VM entrypoint and report the host control plane as degraded instead of treating the VM as broken.

## Validation rules

- Every code change must end with a validation step and a stated residual risk.
- Follow `D:\codex\workflows\POST_CHANGE_VERIFICATION.md` as the default post-change checklist.
- For ToyOS work, refresh any affected report under `D:\codex\generated\toy-os-demo` and keep delivery rooted there.
- For regression surfacing, prefer updating or rerunning machine-readable evidence before writing prose-only summaries.

## Local skills

Use these local playbooks when the task matches:

- `D:\codex\skills\repo-onboard\SKILL.md`: orient to a repo or subsystem and extract runnable commands.
- `D:\codex\skills\bugfix-loop\SKILL.md`: reproduce, patch, validate, and record a bug fix.
- `D:\codex\skills\change-review\SKILL.md`: review a change for regression risk, missing validation, and incomplete delivery.

## Output expectations

- Report what changed, how it was validated, and what remains unverified.
- Include exact file paths for any artifact the operator must inspect.
- Keep summaries short, but make the execution path auditable.
