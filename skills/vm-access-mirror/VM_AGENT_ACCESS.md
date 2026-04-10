# VM Agent Access

This workspace already has a unified entry point to the Linux VM.

Recommended unified entry:
- `E:\codex\vmctl.cmd`

VM target:
- VMX: `D:\VMs\orchestrator-mvp-ubuntu-cloud\orchestrator-mvp-ubuntu-cloud.vmx`
- IP: `192.168.202.130`
- User: `codex`

Low-level entries:
- `E:\codex\vm-ssh.cmd`
- `E:\codex\vm-plink.cmd`
- `E:\codex\vm-run.cmd`
- `E:\codex\vm-pandoc-pdf-zh.cmd`
- `E:\codex\vm-put.cmd`
- `E:\codex\vm-get.cmd`

Self-check:
- `E:\codex\vm-check.cmd`

## Use vmctl First

For another local agent, prefer these forms:

```powershell
E:\codex\vmctl.cmd check
E:\codex\vmctl.cmd doctor
E:\codex\vmctl.cmd ssh uname -a
E:\codex\vmctl.cmd exec uname -a
E:\codex\vmctl.cmd ssh -CommandString "bash -lc 'pwd && whoami'"
E:\codex\vmctl.cmd script E:\codex\tools\vm-smoke.sh
E:\codex\vmctl.cmd plink uname -a
E:\codex\vmctl.cmd put E:\codex\local.txt /tmp/local.txt
E:\codex\vmctl.cmd get /tmp/result.txt E:\codex\output\result.txt
E:\codex\vmctl.cmd pdf E:\codex\doc.md E:\codex\doc.pdf
```

Why this is the preferred entry:
- one command surface for the agent to remember
- no raw `ssh.exe` or `scp.exe`
- optional `plink` route when PuTTY-style CLI is preferable
- avoids host SSH config pollution
- avoids most quoting issues for multi-line shell via `-ScriptPath`

## What Works

Verified in this session:
- `E:\codex\vm-ssh.cmd uname -a`
- `D:\新建文件夹\vmrun.exe -T ws checkToolsState "<vmx>"`
- `D:\新建文件夹\vmrun.exe -T ws -gu codex -gp <password> listProcessesInGuest "<vmx>"`

So:
- SSH is working.
- VMware Tools guest operations are working.

## Use SSH First

Run commands in the VM with:

```powershell
E:\codex\vm-ssh.cmd uname -a
E:\codex\vm-ssh.cmd "cd /home/codex/dev && ls"
E:\codex\vm-ssh.cmd "cd /srv/orchestrator-mvp && docker ps"
```

Important details:
- This wrapper already ignores the host `C:\Users\lenovo\.ssh\config`.
- It already forces `publickey` auth and uses the workspace key.
- Do not call raw `ssh.exe` first unless you know you need custom flags.

For multi-line shell scripts, do not hand-roll quoting. Use:

```powershell
E:\codex\vm-ssh.ps1 -ScriptPath E:\codex\tools\something.sh
```

For an exact remote command string without argument re-joining, use:

```powershell
E:\codex\vm-ssh.ps1 -CommandString "bash -lc 'pwd && whoami'"
```

## Copy Files

Upload a host file into the VM:

```powershell
E:\codex\vm-put.cmd E:\codex\local.txt /tmp/local.txt
```

Download a VM file back to the host:

```powershell
E:\codex\vm-get.cmd /tmp/result.txt E:\codex\output\result.txt
```

## Use vmrun As Fallback

If SSH is blocked by the agent sandbox or permissions, use:

```powershell
$env:CODEX_VM_PASSWORD='CodexVm2026'
E:\codex\vm-run.cmd uname -a
$env:CODEX_VM_PASSWORD='CodexVm2026'
E:\codex\vm-run.cmd "cd /srv/orchestrator-mvp && docker ps"
```

Notes:
- `vm-run.cmd` returns guest stdout.
- `vm-run.cmd` also propagates guest exit codes.
- `vm-run.cmd` depends on `CODEX_VM_PASSWORD` unless a password file is configured.

## Pandoc And LaTeX In The VM

Installed in the VM:
- `pandoc`
- `pdflatex`
- `xelatex`
- `latexmk`
- Chinese LaTeX support for `ctex`

Directly inside the VM:

```powershell
E:\codex\vm-ssh.cmd "pandoc-pdf-zh input.md output.pdf"
E:\codex\vm-ssh.cmd "pandoc input.md -o output.pdf --defaults ~/.config/pandoc/pdf-zh.yaml"
```

From the Windows host or from another agent in this workspace:

```powershell
E:\codex\vm-pandoc-pdf-zh.cmd E:\docs\input.md E:\docs\output.pdf
```

What the host wrapper does:
- uploads the local Markdown file to `/tmp` in the VM
- runs `pandoc-pdf-zh` inside the VM
- downloads the generated PDF back to the requested Windows path

Notes:
- The VM-side defaults file is `~/.config/pandoc/pdf-zh.yaml`
- The VM-side helper command is `/usr/local/bin/pandoc-pdf-zh`
- The host wrapper uses the same SSH key path and VM target as `vm-ssh.cmd`

## PuTTY / plink

Installed on the host:
- `E:\codex\tools\putty\plink.exe`
- `E:\codex\.vm-keys\id_ed25519_host.ppk`

Wrapped entry:
- `E:\codex\vm-plink.cmd`
- `E:\codex\vmctl.cmd plink ...`

The wrapper already pins the VM SSH host key, so batch mode works without manual first-run trust prompts.

## Recommended Agent Flow

For another local agent, the least fragile sequence is:

```powershell
E:\codex\vmctl.cmd check
E:\codex\vmctl.cmd ssh uname -a
E:\codex\vmctl.cmd put E:\codex\somefile /tmp/somefile
E:\codex\vmctl.cmd ssh -ScriptPath E:\codex\tools\work.sh
E:\codex\vmctl.cmd get /tmp/result E:\codex\output\result
```

This avoids:
- raw `ssh.exe`
- raw `scp.exe`
- host SSH config pollution
- most quoting problems with multi-line shell

## Minimal Health Checks

Single-command check:

```powershell
E:\codex\vm-check.cmd
```

SSH check:

```powershell
E:\codex\vm-ssh.cmd uname -a
```

VMware Tools check:

```powershell
& 'D:\新建文件夹\vmrun.exe' -T ws checkToolsState 'D:\VMs\orchestrator-mvp-ubuntu-cloud\orchestrator-mvp-ubuntu-cloud.vmx'
```

Guest operations check:

```powershell
& 'D:\新建文件夹\vmrun.exe' -T ws -gu codex -gp CodexVm2026 listProcessesInGuest 'D:\VMs\orchestrator-mvp-ubuntu-cloud\orchestrator-mvp-ubuntu-cloud.vmx'
```

## If Another Agent Still Says "Channel Not Restored"

That usually means one of these:
- The agent did not use `E:\codex\vm-ssh.cmd`.
- The agent used raw `ssh.exe` and got polluted by host SSH config.
- The agent did not have approval for the required command prefix.
- The agent tried VMware guest operations without the VMX path or guest credentials.

The correct first retry is:

```powershell
E:\codex\vm-ssh.cmd uname -a
```

If that is blocked by permissions, use:

```powershell
$env:CODEX_VM_PASSWORD='CodexVm2026'
E:\codex\vm-run.cmd uname -a
```
