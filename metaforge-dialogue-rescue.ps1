param(
    [string]$Workspace = 'D:\codex'
)

$ErrorActionPreference = 'Stop'

function Read-JsonCommand {
    param([string]$Command)
    $raw = Invoke-Expression $Command | Out-String
    if ([string]::IsNullOrWhiteSpace($raw)) {
        throw "No output from command: $Command"
    }
    return $raw | ConvertFrom-Json
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$archiveDir = 'D:\codex\dialogue-assets'
New-Item -Path $archiveDir -ItemType Directory -Force | Out-Null

$asset = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-dialogue-assetize.ps1'
$compact = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-dialogue-compact.ps1'
$memory = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-memory-snapshot.ps1'
$bootstrap = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\codex-session-bootstrap.ps1'
$dialogueStatus = Read-JsonCommand 'D:\codex\factoryctl.cmd dialogue-status'

$rescue = [ordered]@{
    status = 'ok'
    rescue_type = 'stuck-dialogue-handoff'
    rescued_at = $stamp
    workspace = $Workspace
    safe_to_continue_in_fresh_dialogue = $true
    recommended_next_step = 'open a fresh dialogue and start from the handoff files instead of the stuck thread'
    handoff_files = @(
        'D:\codex\METAFORGE_OS_ACTIVE_DIALOGUE_HANDOFF.md',
        'D:\codex\METAFORGE_OS_ACTIVE_DIALOGUE_SNAPSHOT.json',
        'D:\codex\METAFORGE_OS_CODEX_MULTI_SESSION_BOOTSTRAP.md'
    )
    startup_command = 'D:\codex\codex-session-bootstrap.ps1'
    commands = @(
        'D:\codex\metaforge-memory-snapshot.ps1',
        'D:\codex\metaforge-dialogue-compact.ps1',
        'D:\codex\factoryctl.cmd dialogue-status'
    )
    assetization = $asset
    compaction = $compact
    memory_snapshot = $memory
    bootstrap = $bootstrap
    dialogue_status = $dialogueStatus
}

$rescuePath = Join-Path $archiveDir ("dialogue-rescue-$stamp.json")
($rescue | ConvertTo-Json -Depth 8) | Set-Content -Path $rescuePath -Encoding UTF8
$rescue['rescue_manifest'] = $rescuePath

$rescue | ConvertTo-Json -Depth 8
