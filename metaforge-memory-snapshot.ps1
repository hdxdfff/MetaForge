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

function Read-JsonFileSafe {
    param([string]$Path)
    try {
        if (-not (Test-Path $Path)) { return $null }
        return Get-Content -Path $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

$self = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-self-status.ps1'
$ceo = Read-JsonCommand 'powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-ceo-status.ps1'
$null = Read-JsonCommand 'D:\codex\factoryctl.cmd dialogue-sync-current'
$null = Read-JsonCommand 'D:\codex\factoryctl.cmd dialogue-status --rebuild'
$memoryKernel = Read-JsonFileSafe 'D:\codex\orchestrator-mvp\data\memory_kernel.json'
$contextKernel = Read-JsonFileSafe 'D:\codex\orchestrator-mvp\data\context_kernel.json'
$goalMemory = Read-JsonFileSafe 'D:\codex\orchestrator-mvp\data\goal_memory.json'
$dialogueMemory = Read-JsonFileSafe 'D:\codex\orchestrator-mvp\data\dialogue_memory.json'

$activeRoots = @()
if ($ceo -and $ceo.delivery -and $ceo.delivery.active_task_execution_roots) {
    $activeRoots = @($ceo.delivery.active_task_execution_roots)
}

$topGoals = @()
if ($memoryKernel -and $memoryKernel.top_goals) {
    $topGoals = @($memoryKernel.top_goals | Select-Object -First 3 | ForEach-Object {
        [ordered]@{
            target = $_.target
            status = $_.status
            type = $_.type
        }
    })
}

$recentDecisions = @()
if ($memoryKernel -and $memoryKernel.recent_decisions) {
    $recentDecisions = @($memoryKernel.recent_decisions | Select-Object -First 5 | ForEach-Object {
        [ordered]@{
            type = $_.type
            summary = $_.summary
        }
    })
}

$recentDialogueDecisions = @()
if ($dialogueMemory -and $dialogueMemory.recent_decisions) {
    $recentDialogueDecisions = @($dialogueMemory.recent_decisions | Select-Object -First 5)
}

$recentDialogueTopics = @()
if ($dialogueMemory -and $dialogueMemory.recent_topics) {
    $recentDialogueTopics = @($dialogueMemory.recent_topics | Select-Object -First 6)
}

$sharedDialogueConstraints = @()
if ($dialogueMemory -and $dialogueMemory.shared_constraints) {
    $sharedDialogueConstraints = @($dialogueMemory.shared_constraints | Select-Object -First 6)
}

$activeDialogueSummary = $null
if ($dialogueMemory -and $dialogueMemory.active_handoff) {
    $activeDialogueSummary = $dialogueMemory.active_handoff.summary
}

$dialogueWorkspaces = @()
if ($dialogueMemory -and $dialogueMemory.workspace_refs) {
    $dialogueWorkspaces = @($dialogueMemory.workspace_refs | Select-Object -First 6)
}

$hints = @('ceo-lane', 'chore-lane', 'product-lane', 'research-lane')

$result = [ordered]@{
    system = 'MetaForge OS'
    memory_mode = 'shared-cross-dialogue-memory'
    updated_at = (Get-Date).ToString('s')
    identity_memory = [ordered]@{
        system = 'MetaForge OS'
        operator_surface = 'OpenCode / Codex'
        acting_ceo_surface = 'main dialogue'
        role_split = 'local small model for chores, OpenCode for CEO mediation, runtime for persistent execution'
        hard_constraints = @(
            'preserve target-workspace integrity',
            'no validation means no delivery',
            'provider-only output is not ToyOS success'
        )
    }
    state_memory = [ordered]@{
        control_status = if ($self) { $self.state.control_status } else { 'unknown' }
        active_task_count = if ($self) { $self.state.active_task_count } else { 0 }
        route_drift_count = if ($ceo) { $ceo.delivery.route_drift_count } else { 0 }
        active_execution_roots = $activeRoots
        current_priority = if ($ceo) { $ceo.ceo.current_priority } else { 'unknown' }
        dialogue_session_count = if ($dialogueMemory) { $dialogueMemory.session_count } else { 0 }
        dialogue_message_count = if ($dialogueMemory) { $dialogueMemory.message_count } else { 0 }
    }
    delivery_memory = [ordered]@{
        authoritative_product_workspace = 'D:\codex\generated\toy-os-demo'
        current_active_roots = $activeRoots
        top_goals = $topGoals
        invalid_delivery_risk = if ($ceo -and $ceo.delivery.route_drift_count -gt 0) { 'high' } else { 'low' }
        dialogue_workspaces = $dialogueWorkspaces
    }
    decision_memory = [ordered]@{
        current_contradiction = if ($ceo -and $ceo.delivery.route_drift_count -gt 0) { 'route_drift' } else { 'none_detected' }
        next_action = if ($ceo) { $ceo.ceo.next_best_action } else { 'read state first' }
        recent_decisions = $recentDecisions
        recent_dialogue_decisions = $recentDialogueDecisions
    }
    handoff_memory = [ordered]@{
        lane_hints = $hints
        default_control_tier = 'ceo-review-required unless chore-only is explicit'
        startup_files = @(
            'D:\codex\METAFORGE-OS.md',
            'D:\codex\METAFORGE_OS_CODEX_MULTI_SESSION_BOOTSTRAP.md',
            'D:\codex\METAFORGE_OS_ROLE_SPLIT.md',
            'D:\codex\METAFORGE_OS_CHORE_QUEUE_POLICY.md',
            'D:\codex\METAFORGE_OS_DISPATCH_TEMPLATE.md'
        )
        startup_command = 'D:\codex\codex-session-bootstrap.ps1'
        recent_dialogue_topics = $recentDialogueTopics
        shared_dialogue_constraints = $sharedDialogueConstraints
        active_dialogue_summary = if ($activeDialogueSummary) { $activeDialogueSummary } else { '' }
    }
    dialogue_memory = [ordered]@{
        session_count = if ($dialogueMemory) { $dialogueMemory.session_count } else { 0 }
        message_count = if ($dialogueMemory) { $dialogueMemory.message_count } else { 0 }
        recent_topics = $recentDialogueTopics
        recent_decisions = $recentDialogueDecisions
        shared_constraints = $sharedDialogueConstraints
        active_handoff = if ($dialogueMemory) { $dialogueMemory.active_handoff } else { $null }
    }
}

$result | ConvertTo-Json -Depth 8
