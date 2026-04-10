# VM Access Contract

This workspace uses the Linux VM as the primary execution root.
The Windows host is the control plane and cached state surface.

## Canonical entrypoints

- VM execution: `D:\codex\vm-entry.cmd`
- Orchestrator workflows: `D:\codex\factoryctl.cmd`
- Canonical VM key root: `D:\codex\.vm-keys`
- Canonical primary SSH key: `D:\codex\.vm-keys\id_ed25519_host`
- Compatibility fallback key: `D:\codex\.vm-keys\id_ed25519_strict`

Do not use legacy `E:\codex\...` wrappers when the same capability exists under `D:\codex\...`.
Do not use `E:\codex\.vm-keys` as a runtime key source.

## Supported VM commands

Use only these forms:

```powershell
D:\codex\vm-entry.cmd run <command...>
D:\codex\vm-entry.cmd ssh <command...>
D:\codex\vm-entry.cmd put <host-path> <guest-path>
D:\codex\vm-entry.cmd get <guest-path> <host-path>
```

Examples:

```powershell
D:\codex\vm-entry.cmd run whoami
D:\codex\vm-entry.cmd ssh bash -lc "cd /srv/orchestrator-mvp && pwd"
D:\codex\vm-entry.cmd put D:\codex\local.txt /tmp/local.txt
D:\codex\vm-entry.cmd get /tmp/result.json D:\codex\result.json
```

## Supported control-plane commands

Use `D:\codex\factoryctl.cmd` for:

- `status`
- `doctor`
- `health`
- `ops`
- `verify`
- `inbox`
- `report`
- `dispatch`
- `sync`

Examples:

```powershell
D:\codex\factoryctl.cmd doctor --human
D:\codex\factoryctl.cmd status --human
D:\codex\factoryctl.cmd inbox --open-only
```

## Stability rules

- Treat `vm_ssh_primary` as the only required execution path.
- Treat `vmrun`, VMware Tools, and Guest Ops as optional probe layers only.
- If host-side status is degraded but SSH is healthy, continue working through `D:\codex\vm-entry.cmd`.
- Do not handcraft raw `ssh.exe` or `scp.exe` arguments unless the VM entry wrapper cannot express the action.
- Do not call `vmrun.exe` directly.
- Keep the primary SSH key ACL restricted enough for OpenSSH to accept it.

## Result-code contract

For `D:\codex\factoryctl.cmd` structured commands:

- `0`: live control plane, primary execution path healthy
- `10`: degraded control plane or cached state, primary execution path still healthy
- `20`: primary execution path unavailable

Check these fields first in JSON output:

- `result_code`
- `source`
- `stale`

## Operator interpretation

- `source=live`: data came from the active control plane
- `source=cached_state`: control plane degraded; continue if the task only needs the VM execution root
- `stale=true`: cached snapshot is old enough to require operator caution

## Do not do this

- Do not treat `cached_state` as proof that the VM is broken.
- Do not infer VM failure from `vmrun` probe failure.
- Do not reactivate old `E:\codex\vmctl.cmd` or related legacy wrappers.
