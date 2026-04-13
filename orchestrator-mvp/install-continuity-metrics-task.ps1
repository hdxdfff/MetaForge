param()

$ErrorActionPreference = "Stop"

[ordered]@{
    ok = $false
    status = "frozen"
    reason = "Windows host scheduled task installers have been disabled."
    authority_root = "/srv/orchestrator-mvp"
    host_role = "backup_sync_observer"
    next_step = "Run continuity metrics inside the VM runtime root instead of installing a Windows scheduled task."
    blocked_script = $MyInvocation.MyCommand.Path
} | ConvertTo-Json -Depth 3
