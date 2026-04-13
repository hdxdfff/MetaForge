$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $root "screen-context-mcp.pid"
$pidValue = $null
if (Test-Path $pidFile) {
    $pidValue = Get-Content $pidFile -ErrorAction SilentlyContinue
}
$process = $null
if ($pidValue) {
    $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
}
$portCheck = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
[pscustomobject]@{
    Running = [bool]$process
    Pid = if ($process) { $process.Id } else { $null }
    ListeningOn8765 = [bool]$portCheck
    Url = "http://127.0.0.1:8765/mcp"
}
