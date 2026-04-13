param()

$ErrorActionPreference = 'Stop'

function Read-JsonFileSafe {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    try {
        return Get-Content -Path $Path -Raw | ConvertFrom-Json
    } catch {
        return $null
    }
}

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

$lanes = Read-JsonFileSafe 'D:\codex\dialogue_lanes.json'
$memory = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-memory-snapshot.ps1'
$openLaneProduct = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-open-lane.ps1 -Lane product-lane'
$openLaneResearch = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-open-lane.ps1 -Lane research-lane'
$openLaneChore = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-open-lane.ps1 -Lane chore-lane'
$openLaneCeo = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-open-lane.ps1 -Lane ceo-lane'

$laneMap = @{
    'ceo-lane' = $openLaneCeo
    'product-lane' = $openLaneProduct
    'research-lane' = $openLaneResearch
    'chore-lane' = $openLaneChore
}

$workboard = [ordered]@{
    system = 'MetaForge OS'
    updated_at = (Get-Date).ToString('s')
    contradiction = if ($memory) { $memory.decision_memory.current_contradiction } else { 'unknown' }
    ceo_priority = if ($memory) { $memory.state_memory.current_priority } else { 'unknown' }
    invalid_delivery_risk = if ($memory) { $memory.delivery_memory.invalid_delivery_risk } else { 'unknown' }
    lanes = @()
}

foreach ($lane in @($lanes)) {
    $detail = $laneMap[$lane.lane_type]
    $workboard.lanes += [ordered]@{
        dialogue_id = $lane.dialogue_id
        lane_type = $lane.lane_type
        target_workspace = $lane.target_workspace
        current_goal = $lane.current_goal
        priority = $lane.priority
        merge_policy = $lane.merge_policy
        workspace_locked = $lane.workspace_locked
        control_tier = if ($detail) { $detail.control_tier } else { 'unknown' }
        validation = if ($detail) { $detail.validation } else { 'unknown' }
        next_action = if ($detail) { $detail.next_action } else { 'read lane asset' }
    }
}

$workboard | ConvertTo-Json -Depth 8 | Set-Content -Path 'D:\codex\METAFORGE_OS_LANE_WORKBOARD.json' -Encoding UTF8
$workboard | ConvertTo-Json -Depth 8
