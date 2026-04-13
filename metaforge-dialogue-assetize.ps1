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

$memory = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-memory-snapshot.ps1'
$compact = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-dialogue-compact.ps1'

$archiveDir = 'D:\codex\dialogue-assets'
New-Item -Path $archiveDir -ItemType Directory -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

$archiveNote = @"
# MetaForge OS Dialogue Asset Note

- Archive time: $stamp
- Main contradiction: $($memory.decision_memory.current_contradiction)
- CEO priority: $($memory.state_memory.current_priority)
- Authoritative workspace: $($memory.delivery_memory.authoritative_product_workspace)
- Active execution roots: $([string]::Join(', ', $memory.state_memory.active_execution_roots))
- Invalid delivery risk: $($memory.delivery_memory.invalid_delivery_risk)
- Next bounded action: $($memory.decision_memory.next_action)

## Key decisions
$((@($memory.decision_memory.recent_decisions) | ForEach-Object { '- [' + $_.type + '] ' + $_.summary }) -join "`r`n")

## Startup files
$((@($memory.handoff_memory.startup_files) | ForEach-Object { '- ' + $_ }) -join "`r`n")
"@

$notePath = Join-Path $archiveDir ("dialogue-asset-note-$stamp.md")
$memoryPath = Join-Path $archiveDir ("dialogue-memory-$stamp.json")
$handoffPath = Join-Path $archiveDir ("dialogue-handoff-$stamp.json")

$archiveNote | Set-Content -Path $notePath -Encoding UTF8
($memory | ConvertTo-Json -Depth 8) | Set-Content -Path $memoryPath -Encoding UTF8
($compact | ConvertTo-Json -Depth 8) | Set-Content -Path $handoffPath -Encoding UTF8

$dialogueSync = Read-JsonCommand (@"
D:\codex\factoryctl.cmd dialogue-sync --session-id asset-$stamp --source metaforge-assetize --title "MetaForge dialogue asset $stamp" --workspace "$Workspace" --summary "$($compact.next_action)" --topic dialogue-compaction --topic metaforge-handoff --decision "$($memory.decision_memory.next_action)" --constraint "explicit validation notes required for all delivery claims" --artifact "$memoryPath" --artifact "$handoffPath" --artifact "$notePath"
"@)

$result = [ordered]@{
    status = 'ok'
    archived_at = $stamp
    archive_dir = $archiveDir
    archive_note = $notePath
    memory_asset = $memoryPath
    handoff_asset = $handoffPath
    dialogue_sync = $dialogueSync
}

$result | ConvertTo-Json -Depth 6
