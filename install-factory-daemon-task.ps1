param(
    [string]$TaskName = 'Codex-FactoryDaemon',
    [string]$Launcher = 'D:\codex\run-factory-daemon.cmd'
)

$ErrorActionPreference = 'Stop'

$createArgs = @(
    '/Create'
    '/TN', $TaskName
    '/TR', $Launcher
    '/SC', 'ONLOGON'
    '/RL', 'LIMITED'
    '/F'
)

$create = Start-Process -FilePath 'schtasks.exe' -ArgumentList $createArgs -Wait -PassThru -NoNewWindow
if ($create.ExitCode -ne 0) {
    throw "schtasks.exe /Create failed with exit code $($create.ExitCode)"
}

$run = Start-Process -FilePath 'schtasks.exe' -ArgumentList @('/Run', '/TN', $TaskName) -Wait -PassThru -NoNewWindow
if ($run.ExitCode -ne 0) {
    throw "schtasks.exe /Run failed with exit code $($run.ExitCode)"
}

$query = Start-Process -FilePath 'schtasks.exe' -ArgumentList @('/Query', '/TN', $TaskName, '/V', '/FO', 'LIST') -Wait -PassThru -NoNewWindow -RedirectStandardOutput "$env:TEMP\factory_daemon_task_query.txt"
if ($query.ExitCode -ne 0) {
    throw "schtasks.exe /Query failed with exit code $($query.ExitCode)"
}

$outputPath = Join-Path $env:TEMP 'factory_daemon_task_query.txt'
$text = if (Test-Path $outputPath) { Get-Content -Path $outputPath -Raw } else { '' }

[pscustomobject]@{
    task_name = $TaskName
    launcher = $Launcher
    task_query = $text
} | ConvertTo-Json -Depth 4
