param()

$selfModelPath = 'D:\codex\orchestrator-mvp\data\self_model_runtime.json'
if (-not (Test-Path $selfModelPath)) {
  & 'D:\codex\factoryctl.cmd' self-model | Out-Null
}

$model = Get-Content -Raw -Encoding UTF8 $selfModelPath | ConvertFrom-Json
$result = [ordered]@{
  identity = [ordered]@{
    name = $model.identity.name
    type = $model.identity.type
    mission = $model.identity.mission
  }
  state = [ordered]@{
    health = $model.state.health
    control_status = $model.state.control_status
    autonomy_stage = $model.state.autonomy.stage
    autonomy_score = $model.state.autonomy.score
    autonomy_level = $model.state.autonomy.level
    daemon_status = $model.state.daemon.status
    daemon_running = $model.state.daemon.running
    daemon_last_error = $model.state.daemon.last_error
    active_task_count = $model.state.tasks.active_count
    waiting_approval_count = $model.state.tasks.waiting_approval_count
    open_error_count = $model.state.escalations.open_error_count
    patch_gate_status = $model.state.verification.patch_gate_status
    quality_status = $model.state.quality.status
    quality_score = $model.state.quality.score
  }
  goal = $model.goal
  next_actions = $model.next_actions
  blockers = $model.state.blockers
  active_tasks = $model.state.tasks.active
}
if ($model.execution) {
  $result.execution = [ordered]@{
    executed_action_count = $model.execution.executed_action_count
    results = $model.execution.results
  }
}
if ($model.reflection) {
  $result.reflection = $model.reflection
}
$result.world = $model.world
$result | ConvertTo-Json -Depth 7
