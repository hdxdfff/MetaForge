param()

$ErrorActionPreference = "Stop"

[ordered]@{
    ok = $false
    status = "observer_only_host"
    reason = "Windows host watchdog and daemon recovery have been disabled as autonomous runtime entrypoints."
    authority_root = "/srv/orchestrator-mvp"
    host_role = "backup_sync_observer"
    next_step = "Use the VM control path for manual daemon recovery instead of local watchdog restart logic."
    blocked_script = $MyInvocation.MyCommand.Path
} | ConvertTo-Json -Depth 3

exit 1
