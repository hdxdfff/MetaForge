$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $root "screen-context-mcp.pid"
if (Test-Path $pidFile) {
    $existingPid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($existingPid) {
        $running = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($running) {
            Write-Output "screen-context-mcp is already running with PID $existingPid"
            exit 0
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}
$python = 'D:\codex\tools\python311-embed\pythonw.exe'
$server = Join-Path $root "server.py"
$proc = Start-Process -FilePath $python -ArgumentList @($server, '--host', '0.0.0.0', '--port', '8765') -WorkingDirectory $root -WindowStyle Hidden -PassThru
Set-Content -Path $pidFile -Value $proc.Id
Write-Output "Started screen-context-mcp host process with PID $($proc.Id)"
