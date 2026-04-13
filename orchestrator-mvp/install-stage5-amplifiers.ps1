param()

$ErrorActionPreference = "Stop"

[ordered]@{
    ok = $false
    status = "frozen"
    reason = "Windows host scheduled task installers have been disabled."
    authority_root = "/srv/orchestrator-mvp"
    host_role = "backup_sync_observer"
    next_step = "Run stage5 amplifiers inside the VM runtime root instead of installing Windows scheduled tasks."
    blocked_script = $MyInvocation.MyCommand.Path
} | ConvertTo-Json -Depth 3
