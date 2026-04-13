param()

$identityPath = 'D:\codex\METAFORGE_OS_SYSTEM_IDENTITY.json'
$worldPath = 'D:\codex\METAFORGE_OS_WORLD_MODEL.json'
$dataRoot = 'D:\codex\orchestrator-mvp\data'
$toyosRoot = 'D:\codex\generated\toy-os-demo'

$identity = Get-Content -Raw -Encoding UTF8 $identityPath | ConvertFrom-Json
$world = Get-Content -Raw -Encoding UTF8 $worldPath | ConvertFrom-Json
$control = Get-Content -Raw -Encoding UTF8 (Join-Path $dataRoot 'control_center_state.json') | ConvertFrom-Json
$hot = Get-Content -Raw -Encoding UTF8 (Join-Path $dataRoot 'hot_context.json') | ConvertFrom-Json
$autonomy = Get-Content -Raw -Encoding UTF8 (Join-Path $dataRoot 'autonomy_score.json') | ConvertFrom-Json
$quality = Get-Content -Raw -Encoding UTF8 (Join-Path $dataRoot 'quality_status.json') | ConvertFrom-Json

$activeTasks = @()
if ($hot.active_tasks) { $activeTasks = @($hot.active_tasks) }

$routeDrift = @($activeTasks | Where-Object {
  $_.repo_path -and $_.repo_path -ne $toyosRoot -and $_.repo_path -like 'D:\codex\orchestrator-mvp\workspace\*'
})

$priority = 'green'
if ($routeDrift.Count -gt 0) { $priority = 'orange' }
if ($hot.open_escalation_count -gt 0 -or $hot.failed_task_count -gt 0) { $priority = 'red' }
elseif ($hot.active_task_count -eq 0) { $priority = 'yellow' }

$ceoDecision = [ordered]@{
  current_priority = $priority
  current_focus = if ($routeDrift.Count -gt 0) { 'contain route drift and restore target-workspace integrity' } else { 'continue bounded verified delivery' }
  should_degrade = ($routeDrift.Count -gt 0)
  should_escalate = ($hot.open_escalation_count -gt 0 -or $hot.failed_task_count -gt 0)
  next_best_action = if ($routeDrift.Count -gt 0) {
    'prefer patch proposal or direct local ToyOS work until routing integrity is repaired'
  } else {
    'continue bounded dispatch with validation-first policy'
  }
}

$result = [ordered]@{
  identity = [ordered]@{
    name = $identity.name
    mission = $identity.mission
    type = $identity.type
  }
  state = [ordered]@{
    control_status = $control.status
    active_task_count = $hot.active_task_count
    failed_task_count = $hot.failed_task_count
    open_escalation_count = $hot.open_escalation_count
    autonomy_stage = $autonomy.stage
    autonomy_score = $autonomy.score
    quality_status = $quality.status
    quality_score = $quality.overall_score
  }
  delivery = [ordered]@{
    target_workspace = $toyosRoot
    active_task_execution_roots = @($activeTasks | ForEach-Object { $_.repo_path } | Select-Object -Unique)
    route_drift_count = $routeDrift.Count
    route_drift_task_ids = @($routeDrift | ForEach-Object { $_.id })
  }
  world = [ordered]@{
    workspace_root = $world.workspace_root
    runtime_surfaces = $world.runtime_surfaces
    tooling_expectations = $world.tooling_expectations
  }
  ceo = $ceoDecision
}

$result | ConvertTo-Json -Depth 6
