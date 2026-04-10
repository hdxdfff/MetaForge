param()

$ErrorActionPreference = "Stop"

[ordered]@{
    ok = $false
    status = "observer_only_host"
    reason = "Windows host local daemon startup has been disabled."
    authority_root = "/srv/orchestrator-mvp"
    host_role = "backup_sync_observer"
    next_step = "Start or recover the daemon through the VM control path, not from the Windows host."
    blocked_script = $MyInvocation.MyCommand.Path
} | ConvertTo-Json -Depth 3

exit 1
