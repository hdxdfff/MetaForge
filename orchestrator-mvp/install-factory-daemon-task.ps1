param()

$ErrorActionPreference = "Stop"

[ordered]@{
    ok = $false
    status = "frozen"
    reason = "Windows host is no longer a live daemon host."
    authority_root = "/srv/orchestrator-mvp"
    host_role = "backup_sync_observer"
    next_step = "Install or operate the daemon inside the VM runtime root instead of creating a Windows scheduled task."
    blocked_script = $MyInvocation.MyCommand.Path
} | ConvertTo-Json -Depth 3
