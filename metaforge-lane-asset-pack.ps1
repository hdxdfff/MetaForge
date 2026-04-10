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

$packDir = 'D:\codex\lane-assets'
New-Item -Path $packDir -ItemType Directory -Force | Out-Null

$common = [ordered]@{
    system = 'MetaForge OS'
    contradiction = $memory.decision_memory.current_contradiction
    ceo_priority = $memory.state_memory.current_priority
    startup_files = $memory.handoff_memory.startup_files
    startup_command = $memory.handoff_memory.startup_command
    next_action = $memory.decision_memory.next_action
}

$packs = @(
    [ordered]@{
        lane = 'ceo-lane'
        authoritative_workspace = 'D:\codex'
        control_tier = 'ceo-review-required'
        validation = 'explicit validation notes for any accepted delivery or routing decision'
        focus = @('route drift', 'lane arbitration', 'dispatch approval', 'invalid delivery containment')
        active_execution_roots = $memory.state_memory.active_execution_roots
        invalid_delivery_risk = $memory.delivery_memory.invalid_delivery_risk
    },
    [ordered]@{
        lane = 'product-lane'
        authoritative_workspace = $memory.delivery_memory.authoritative_product_workspace
        control_tier = 'ceo-review-required unless report-only'
        validation = 'product artifact must land in authoritative workspace with validation notes'
        focus = @('ToyOS bounded delivery', 'workspace integrity', 'syscall/scheduler/paging/docs/tests')
        active_execution_roots = $memory.state_memory.active_execution_roots
        invalid_delivery_risk = $memory.delivery_memory.invalid_delivery_risk
    },
    [ordered]@{
        lane = 'research-lane'
        authoritative_workspace = 'D:\codex'
        control_tier = 'ceo-review-required'
        validation = 'policy or architecture claims must cite current local state or docs'
        focus = @('routing', 'KPI', 'memory', 'self-improvement')
        active_execution_roots = $memory.state_memory.active_execution_roots
        invalid_delivery_risk = $memory.delivery_memory.invalid_delivery_risk
    },
    [ordered]@{
        lane = 'chore-lane'
        authoritative_workspace = 'D:\codex'
        control_tier = 'chore-only'
        validation = 'static review, state cross-check, or file presence check'
        focus = @('digests', 'inventories', 'reports', 'formatting')
        active_execution_roots = $memory.state_memory.active_execution_roots
        invalid_delivery_risk = $memory.delivery_memory.invalid_delivery_risk
    }
)

$outputs = @()
foreach ($pack in $packs) {
    $payload = [ordered]@{}
    foreach ($k in $common.Keys) { $payload[$k] = $common[$k] }
    foreach ($k in $pack.Keys) { $payload[$k] = $pack[$k] }

    $jsonPath = Join-Path $packDir ($pack.lane + '.json')
    $mdPath = Join-Path $packDir ($pack.lane + '.md')

    ($payload | ConvertTo-Json -Depth 8) | Set-Content -Path $jsonPath -Encoding UTF8

    $md = @"
# MetaForge OS Lane Asset Pack

- Lane: $($pack.lane)
- Authoritative workspace: $($pack.authoritative_workspace)
- Contradiction: $($common.contradiction)
- CEO priority: $($common.ceo_priority)
- Control tier: $($pack.control_tier)
- Validation: $($pack.validation)
- Next action: $($common.next_action)
- Invalid delivery risk: $($pack.invalid_delivery_risk)

## Focus
$((@($pack.focus) | ForEach-Object { '- ' + $_ }) -join "`r`n")

## Startup files
$((@($common.startup_files) | ForEach-Object { '- ' + $_ }) -join "`r`n")

## Startup command
- $($common.startup_command)
"@

    $md | Set-Content -Path $mdPath -Encoding UTF8

    $outputs += [ordered]@{
        lane = $pack.lane
        json = $jsonPath
        markdown = $mdPath
    }
}

$result = [ordered]@{
    status = 'ok'
    pack_dir = $packDir
    outputs = $outputs
}

$result | ConvertTo-Json -Depth 8
