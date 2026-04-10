param(
    [string]$Workspace = 'D:\codex'
)

$ErrorActionPreference = 'Stop'

function Read-JsonCommand {
    param([string]$Command)
    try {
        $raw = Invoke-Expression $Command | Out-String
        if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
        return $raw | ConvertFrom-Json
    } catch {
        return $null
    }
}

$memory = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-memory-snapshot.ps1'
$bootstrap = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\codex-session-bootstrap.ps1'

if (-not $memory) {
    throw 'Shared memory snapshot unavailable.'
}

$snapshot = [ordered]@{
    system = 'MetaForge OS'
    snapshot_type = 'dialogue-compaction'
    updated_at = (Get-Date).ToString('s')
    contradiction = $memory.decision_memory.current_contradiction
    ceo_priority = $memory.state_memory.current_priority
    lane_hint = 'ceo-lane'
    authoritative_workspace = $memory.delivery_memory.authoritative_product_workspace
    control_tier = $memory.handoff_memory.default_control_tier
    required_validation = 'explicit validation notes required for all delivery claims'
    active_task_count = $memory.state_memory.active_task_count
    active_execution_roots = $memory.state_memory.active_execution_roots
    invalid_delivery_risk = $memory.delivery_memory.invalid_delivery_risk
    startup_files = $memory.handoff_memory.startup_files
    startup_command = $memory.handoff_memory.startup_command
    next_action = $memory.decision_memory.next_action
}

$snapshot | ConvertTo-Json -Depth 8 | Set-Content -Path 'D:\codex\METAFORGE_OS_ACTIVE_DIALOGUE_SNAPSHOT.json' -Encoding UTF8

$handoff = @"
# MetaForge OS Active Dialogue Handoff

- System: MetaForge OS
- Snapshot type: dialogue-compaction
- Contradiction: $($snapshot.contradiction)
- CEO priority: $($snapshot.ceo_priority)
- Lane hint: $($snapshot.lane_hint)
- Authoritative workspace: $($snapshot.authoritative_workspace)
- Control tier: $($snapshot.control_tier)
- Required validation: $($snapshot.required_validation)
- Active task count: $($snapshot.active_task_count)
- Active execution roots: $([string]::Join(', ', $snapshot.active_execution_roots))
- Invalid delivery risk: $($snapshot.invalid_delivery_risk)
- Next action: $($snapshot.next_action)

Read first:
$((@($snapshot.startup_files) | ForEach-Object { '- ' + $_ }) -join "`r`n")

Startup command:
- $($snapshot.startup_command)
"@

$handoff | Set-Content -Path 'D:\codex\METAFORGE_OS_ACTIVE_DIALOGUE_HANDOFF.md' -Encoding UTF8

$snapshot | ConvertTo-Json -Depth 8
