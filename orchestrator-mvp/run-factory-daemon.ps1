param()

$ErrorActionPreference = "Stop"

[ordered]@{
    ok = $false
    status = "observer_only_host"
    reason = "Windows host local daemon execution has been disabled."
    authority_root = "/srv/orchestrator-mvp"
    host_role = "backup_sync_observer"
    next_step = "Run the daemon inside the VM runtime root if execution is required."
    blocked_script = $MyInvocation.MyCommand.Path
} | ConvertTo-Json -Depth 3

exit 1
