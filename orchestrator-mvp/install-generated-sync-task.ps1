Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$taskName = "MetaForgeGeneratedSync"
$scriptPath = "D:\codex\orchestrator-mvp\sync-vm-generated.ps1"
$powershellExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$schtasksExe = "$env:SystemRoot\System32\schtasks.exe"

if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Sync script not found: $scriptPath"
}

if (-not (Test-Path -LiteralPath $schtasksExe)) {
    throw "schtasks.exe not found: $schtasksExe"
}

$taskCommand = '"' + $powershellExe + '" -NoProfile -ExecutionPolicy Bypass -File "' + $scriptPath + '"'

& $schtasksExe /Create /TN $taskName /SC MINUTE /MO 5 /TR $taskCommand /F | Out-Null

[pscustomobject]@{
    status = "installed"
    task = $taskName
    schedule = "every 5 minutes"
    command = $taskCommand
} | ConvertTo-Json -Depth 4
