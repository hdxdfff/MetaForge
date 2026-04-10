param()

$self = powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-self-status.ps1 | ConvertFrom-Json
$ceo = powershell -ExecutionPolicy Bypass -File D:\codex\metaforge-ceo-status.ps1 | ConvertFrom-Json

$topIssue = if ($ceo.delivery.route_drift_count -gt 0) {
  'route_drift'
} elseif ($ceo.state.open_escalation_count -gt 0) {
  'open_escalations'
} elseif ($ceo.state.failed_task_count -gt 0) {
  'failed_tasks'
} else {
  'throughput_optimization'
}

$recommendedMode = switch ($topIssue) {
  'route_drift' { 'patch_proposal_or_direct_local_delivery' }
  'open_escalations' { 'escalate_or_resolve' }
  'failed_tasks' { 'bounded_repair' }
  default { 'bounded_scaling' }
}

$targets = switch ($topIssue) {
  'route_drift' { @('routing guard', 'workspace lock', 'lane-aware dispatch') }
  'open_escalations' { @('resolve inbox', 'reduce ambiguity') }
  'failed_tasks' { @('diagnose failures', 'repair validation path') }
  default { @('increase verified throughput', 'expand automation carefully') }
}

$result = [ordered]@{
  identity = $self.identity
  current_state = $ceo.state
  top_contradiction = $topIssue
  current_priority = $ceo.ceo.current_priority
  recommended_mode = $recommendedMode
  recommended_targets = $targets
  next_action = $ceo.ceo.next_best_action
  self_improvement_allowed = $true
  guardrail = 'Do not weaken target workspace integrity or verification while improving autonomy.'
}

$result | ConvertTo-Json -Depth 6
