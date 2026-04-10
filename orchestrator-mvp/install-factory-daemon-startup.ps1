param()

$ErrorActionPreference = "Stop"

[ordered]@{
    ok = $false
    status = "frozen"
    reason = "Windows host startup is no longer allowed to launch the live daemon."
    authority_root = "/srv/orchestrator-mvp"
    host_role = "backup_sync_observer"
    next_step = "Use the VM runtime root for daemon startup and recovery; keep the Windows host as sync and observation only."
    blocked_script = $MyInvocation.MyCommand.Path
} | ConvertTo-Json -Depth 3
