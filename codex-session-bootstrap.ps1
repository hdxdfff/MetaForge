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

$self = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-self-status.ps1'
$ceo = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-ceo-status.ps1'
$memory = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-memory-snapshot.ps1'
$llmConfig = $null
try {
    $llmConfig = Get-Content -Path 'D:\codex\METAFORGE_OS_LOCAL_LLM_CONFIG.json' -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    $llmConfig = $null
}

$result = [ordered]@{
    system = 'MetaForge OS'
    workspace = $Workspace
    bootstrap_mode = 'codex-multi-session'
    acting_ceo_surface = 'OpenCode/Codex main dialogue'
    lane_hints = if ($memory) { $memory.handoff_memory.lane_hints } else { @('ceo-lane', 'chore-lane', 'product-lane', 'research-lane') }
    default_rules = @(
        'preserve target-workspace integrity',
        'no validation means no delivery',
        'local-model outputs are drafts unless chore-only',
        'ToyOS delivery must land in D:\codex\generated\toy-os-demo'
    )
    preferred_entrypoints = if ($memory) { $memory.handoff_memory.startup_files } else { @('D:\codex\METAFORGE-OS.md') }
    commands = @(
        'D:\codex\metaforge-memory-snapshot.ps1',
        'D:\codex\metaforge-self-status.ps1',
        'D:\codex\metaforge-ceo-status.ps1',
        'D:\codex\metaforge-local-llm-status.ps1',
        'D:\codex\factoryctl.cmd dialogue-status'
    )
    control_status = if ($self) { $self.state.control_status } else { 'unknown' }
    active_task_count = if ($self) { $self.state.active_task_count } else { 0 }
    active_task_roots = if ($ceo) { @($ceo.delivery.active_task_execution_roots) } else { @() }
    route_drift_count = if ($ceo) { $ceo.delivery.route_drift_count } else { 0 }
    local_llm_configured = if ($llmConfig) { $llmConfig.enabled } else { $false }
    memory_snapshot_ready = if ($memory) { $true } else { $false }
    current_contradiction = if ($memory) { $memory.decision_memory.current_contradiction } else { 'unknown' }
    next_action = if ($memory) { $memory.decision_memory.next_action } else { 'use lane-specific bounded work and require CEO review for code, routing, boundary, or policy changes' }
    shared_dialogue_memory_ready = if ($memory -and $memory.dialogue_memory) { $true } else { $false }
    dialogue_session_count = if ($memory -and $memory.dialogue_memory) { $memory.dialogue_memory.session_count } else { 0 }
    recent_dialogue_topics = if ($memory) { @($memory.handoff_memory.recent_dialogue_topics) } else { @() }
    active_dialogue_summary = if ($memory) { $memory.handoff_memory.active_dialogue_summary } else { '' }
}

$result | ConvertTo-Json -Depth 8

