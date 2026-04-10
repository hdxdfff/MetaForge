from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    queued = "queued"
    planning = "planning"
    running = "running"
    execution_finished = "execution_finished"
    verification_pending = "verification_pending"
    verification_running = "verification_running"
    verification_passed = "verification_passed"
    verification_failed = "verification_failed"
    delivery_ready = "delivery_ready"
    released = "released"
    archived = "archived"
    cancelled = "cancelled"
    waiting_approval = "waiting_approval"
    completed = "completed"
    failed = "failed"
    timed_out = "timed_out"


class StepStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class WorkerType(str, Enum):
    planner = "planner"
    coder = "coder"
    shell = "shell"
    docker = "docker"
    browser = "browser"
    reviewer = "reviewer"
    publisher = "publisher"


class AgentRole(str, Enum):
    supervisor = "supervisor"
    product = "product"
    architect = "architect"
    coder = "coder"
    tester = "tester"
    reviewer = "reviewer"
    ops = "ops"


class ResourceKind(str, Enum):
    runtime = "runtime"
    model = "model"
    tool = "tool"
    ide = "ide"
    vcs = "vcs"
    container = "container"


class ContextMode(str, Enum):
    lean = "lean"
    standard = "standard"
    deep = "deep"


class ExecutionMode(str, Enum):
    governance = "governance"
    research = "research"
    production = "production"


class PublicationStatus(str, Enum):
    draft = "draft"
    approved = "approved"
    published = "published"
    rejected = "rejected"

class StepSpec(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    title: str
    worker: WorkerType
    instructions: str
    phase: str | None = None
    command: str | None = None
    workdir: str | None = None
    assigned_role: AgentRole | None = None
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    status: StepStatus = StepStatus.pending
    output: str | None = None
    output_ref: dict[str, Any] = Field(default_factory=dict)
    output_stats: dict[str, Any] = Field(default_factory=dict)
    probe_attempts: int = 0
    max_probe_attempts: int = 1
    last_diagnosis: str | None = None
    last_diagnosis_ref: dict[str, Any] = Field(default_factory=dict)


class ArtifactSpec(BaseModel):
    artifact_id: str | None = None
    artifact_type: str = 'artifact'
    type: str = 'artifact'
    output: str | None = None
    entrypoint: str | None = None
    deliverables: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    required_artifacts: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)
    registry: str | None = None
    test_command: str | None = None
    min_fresh_artifacts: int = 1


class VerificationContract(BaseModel):
    verification_level: str = "L1"
    required_checks: list[str] = Field(default_factory=list)
    artifact_requirements: dict[str, Any] = Field(default_factory=dict)
    release_gate: str = "all_required_checks_pass"
    failure_policy: str = "return_to_planner"
    evidence_requirements: list[str] = Field(default_factory=list)
    verification_notes: list[str] = Field(default_factory=list)


class TaskCreate(BaseModel):
    prompt: str = Field(min_length=8)
    title: str | None = None
    repo_path: str | None = None
    project_id: str | None = None
    goal: str | None = None
    goal_id: str | None = None
    graph_id: str | None = None
    node_id: str | None = None
    scheduled_by: str | None = None
    auto_approve: bool = False
    context_mode: ContextMode = ContextMode.lean
    max_context_chars: int = 1600
    allow_resource_scan: bool = True
    allow_repo_status: bool = True
    capability_route: CapabilityRoute | None = None
    platform_context: dict[str, Any] = Field(default_factory=dict)
    vm_template: dict[str, Any] | None = None
    vm_context: dict[str, Any] = Field(default_factory=dict)
    execution_mode: ExecutionMode = ExecutionMode.governance
    preferred_worker: str | None = None
    scheduler_hint: dict[str, Any] = Field(default_factory=dict)
    context_package: dict[str, Any] = Field(default_factory=dict)
    tool_route: dict[str, Any] = Field(default_factory=dict)
    executor_hint: dict[str, Any] = Field(default_factory=dict)
    execution_lane: str = 'host-control'
    worker_vm_policy: dict[str, Any] = Field(default_factory=dict)
    prompt_guard: dict[str, Any] = Field(default_factory=dict)
    tool_policy: dict[str, Any] = Field(default_factory=dict)
    security_review: dict[str, Any] = Field(default_factory=dict)
    artifact_spec: ArtifactSpec | None = None
    verification_contract: VerificationContract | None = None
    task_type: str | None = None
    queue_name: str | None = None
    verification_level: str | None = None
    max_runtime_seconds: int | None = None
    retry_limit: int | None = None
    rollback_rule: str | None = None
    plan: list[StepSpec] = Field(default_factory=list)
    parent_task_id: str | None = None
    root_task_id: str | None = None
    decomposition_depth: int = 0
    max_decomposition_depth: int = 2
    admission_lane: str | None = None
    admission_reason: str | None = None
    dependency_task_ids: list[str] = Field(default_factory=list)
    verification_signals: list[dict[str, Any]] = Field(default_factory=list)
    goal_admission: dict[str, Any] = Field(default_factory=dict)


class TaskPublicationRequest(BaseModel):
    title: str = Field(min_length=3)
    prompt: str = Field(min_length=8)
    task_type: str = Field(min_length=2)
    verification_level: str = Field(min_length=2)
    repo_path: str | None = None
    project_id: str | None = None
    goal: str | None = None
    goal_id: str | None = None
    graph_id: str | None = None
    node_id: str | None = None
    scheduled_by: str = "task-publish"
    auto_approve: bool = False
    context_mode: ContextMode = ContextMode.lean
    max_context_chars: int = 1600
    allow_resource_scan: bool = True
    allow_repo_status: bool = True
    capability_route: CapabilityRoute | None = None
    platform_context: dict[str, Any] = Field(default_factory=dict)
    vm_template: dict[str, Any] | None = None
    vm_context: dict[str, Any] = Field(default_factory=dict)
    execution_mode: ExecutionMode = ExecutionMode.governance
    preferred_worker: str | None = None
    scheduler_hint: dict[str, Any] = Field(default_factory=dict)
    context_package: dict[str, Any] = Field(default_factory=dict)
    tool_route: dict[str, Any] = Field(default_factory=dict)
    executor_hint: dict[str, Any] = Field(default_factory=dict)
    execution_lane: str = "host-control"
    worker_vm_policy: dict[str, Any] = Field(default_factory=dict)
    prompt_guard: dict[str, Any] = Field(default_factory=dict)
    tool_policy: dict[str, Any] = Field(default_factory=dict)
    security_review: dict[str, Any] = Field(default_factory=dict)
    artifact_spec: ArtifactSpec | None = None
    verification_contract: VerificationContract | None = None
    queue_name: str | None = None
    max_runtime_seconds: int | None = None
    retry_limit: int | None = None
    rollback_rule: str | None = None
    plan: list[StepSpec] = Field(default_factory=list)
    goal_admission: dict[str, Any] = Field(default_factory=dict)


class TaskPublicationRecord(BaseModel):
    publication_id: str = Field(default_factory=lambda: uuid4().hex)
    status: PublicationStatus = PublicationStatus.draft
    title: str
    prompt: str
    task_type: str
    verification_level: str
    repo_path: str | None = None
    project_id: str | None = None
    goal: str | None = None
    goal_id: str | None = None
    graph_id: str | None = None
    node_id: str | None = None
    scheduled_by: str = "task-publish"
    auto_approve: bool = False
    context_mode: ContextMode = ContextMode.lean
    max_context_chars: int = 1600
    allow_resource_scan: bool = True
    allow_repo_status: bool = True
    capability_route: CapabilityRoute | None = None
    platform_context: dict[str, Any] = Field(default_factory=dict)
    vm_template: dict[str, Any] | None = None
    vm_context: dict[str, Any] = Field(default_factory=dict)
    execution_mode: ExecutionMode = ExecutionMode.governance
    preferred_worker: str | None = None
    scheduler_hint: dict[str, Any] = Field(default_factory=dict)
    context_package: dict[str, Any] = Field(default_factory=dict)
    tool_route: dict[str, Any] = Field(default_factory=dict)
    executor_hint: dict[str, Any] = Field(default_factory=dict)
    execution_lane: str = "host-control"
    worker_vm_policy: dict[str, Any] = Field(default_factory=dict)
    prompt_guard: dict[str, Any] = Field(default_factory=dict)
    tool_policy: dict[str, Any] = Field(default_factory=dict)
    security_review: dict[str, Any] = Field(default_factory=dict)
    artifact_spec: ArtifactSpec | None = None
    verification_contract: VerificationContract | None = None
    queue_name: str | None = None
    max_runtime_seconds: int | None = None
    retry_limit: int | None = None
    rollback_rule: str | None = None
    plan: list[StepSpec] = Field(default_factory=list)
    goal_admission: dict[str, Any] = Field(default_factory=dict)
    task_id: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    published_by: str | None = None
    published_at: datetime | None = None
    approval_notes: str | None = None
    publication_notes: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TaskPublicationApproveRequest(BaseModel):
    approved_by: str | None = None
    notes: str | None = None


class TaskPublicationPublishRequest(BaseModel):
    published_by: str | None = None
    notes: str | None = None


class DispatchTaskRequest(BaseModel):
    prompt: str = Field(min_length=8)
    title: str | None = None
    project_id: str | None = None
    repo_id: str | None = None
    repo_path: str | None = None
    goal: str | None = None
    goal_id: str | None = None
    graph_id: str | None = None
    node_id: str | None = None
    scheduled_by: str | None = None
    caller: str = "chat"
    auto_approve: bool = False
    context_mode: ContextMode | None = None
    max_context_chars: int | None = None
    allow_resource_scan: bool = True
    allow_repo_status: bool = True
    enqueue_only: bool = False
    capability_request: str | None = None
    vm_request: str | None = None
    execution_mode: ExecutionMode | None = None
    preferred_worker: str | None = None
    scheduler_hint: dict[str, Any] = Field(default_factory=dict)
    context_package: dict[str, Any] = Field(default_factory=dict)
    tool_route: dict[str, Any] = Field(default_factory=dict)
    executor_hint: dict[str, Any] = Field(default_factory=dict)
    execution_lane: str = 'host-control'
    worker_vm_policy: dict[str, Any] = Field(default_factory=dict)
    prompt_guard: dict[str, Any] = Field(default_factory=dict)
    tool_policy: dict[str, Any] = Field(default_factory=dict)
    security_review: dict[str, Any] = Field(default_factory=dict)
    artifact_spec: ArtifactSpec | None = None
    verification_contract: VerificationContract | None = None
    task_type: str | None = None
    queue_name: str | None = None
    verification_level: str | None = None
    max_runtime_seconds: int | None = None
    retry_limit: int | None = None
    rollback_rule: str | None = None
    parent_task_id: str | None = None
    root_task_id: str | None = None
    decomposition_depth: int = 0
    max_decomposition_depth: int = 2
    admission_lane: str | None = None
    admission_reason: str | None = None
    dependency_task_ids: list[str] = Field(default_factory=list)
    verification_signals: list[dict[str, Any]] = Field(default_factory=list)
    goal_admission: dict[str, Any] = Field(default_factory=dict)


class GoalAdmissionRequest(BaseModel):
    goal: str = Field(min_length=8)
    title: str | None = None
    prompt: str | None = None
    project_id: str | None = None
    repo_path: str | None = None
    goal_id: str | None = None
    scheduled_by: str | None = None
    context_mode: ContextMode = ContextMode.standard
    max_context_chars: int = 1600
    allow_resource_scan: bool = True
    allow_repo_status: bool = True
    execution_mode: ExecutionMode = ExecutionMode.research
    preferred_worker: str | None = None
    execution_lane: str = "host-control"
    auto_approve: bool = False
    strategy: str | None = None
    task_type: str | None = None
    queue_name: str | None = None
    verification_level: str | None = None
    artifact_spec: ArtifactSpec | None = None
    verification_contract: VerificationContract | None = None
    scheduler_hint: dict[str, Any] = Field(default_factory=dict)
    goal_admission: dict[str, Any] = Field(default_factory=dict)

class AutoDebugRequest(BaseModel):
    error_text: str = Field(min_length=4)
    repo_path: str | None = None
    workspace: str | None = None
    project_id: str | None = None
    repo_id: str | None = None
    goal: str | None = None
    prompt: str | None = None
    failing_command: str | None = None
    failing_output: str | None = None
    caller: str = "auto-debug"
    auto_approve: bool = False
    context_mode: ContextMode | None = None
    max_context_chars: int | None = None
    allow_resource_scan: bool = True
    allow_repo_status: bool = True

class TaskEvent(BaseModel):
    timestamp: datetime = Field(default_factory=utc_now)
    level: str = "info"
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class ContextEnvelope(BaseModel):
    mode: ContextMode
    budget_chars: int
    used_chars: int = 0
    includes: list[str] = Field(default_factory=list)
    summary_blocks: list[str] = Field(default_factory=list)


class CheapLaneState(BaseModel):
    calls_used: int = 0
    chars_used: int = 0
    blocked: bool = False
    block_reason: str | None = None
    repeated_output_count: int = 0
    last_worker: str | None = None
    last_output_fingerprint: str | None = None


class TaskContract(BaseModel):
    requirements: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    artifact_spec: ArtifactSpec | None = None


class AuditCoderOutput(BaseModel):
    target_files: list[str] = Field(default_factory=list)
    smallest_gap: str = ""
    patch_plan: str = ""
    validation_commands: list[str] = Field(default_factory=list)
    residual_risk: str = ""


class AuditReviewerOutput(BaseModel):
    verdict: str = ""
    evidence_checked: list[str] = Field(default_factory=list)
    validation_status: str = ""
    regression_risks: list[str] = Field(default_factory=list)
    follow_up_patch: str = ""
    next_action: str = ""


class RuleCheck(BaseModel):
    name: str
    status: str = "pending"
    detail: str = ""


class GitWorkflowState(BaseModel):
    enabled: bool = False
    repo_registered: bool = False
    branch_required: bool = True
    branch_name: str | None = None
    commit_required: bool = True
    pr_required: bool = True
    status_summary: str | None = None


class AgentAssignment(BaseModel):
    role: AgentRole
    responsibility: str
    status: str = "planned"




class ProductDesign(BaseModel):
    summary: str = ""
    user_stories: list[str] = Field(default_factory=list)
    api_surfaces: list[str] = Field(default_factory=list)
    pages_or_flows: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ArchitectureDesign(BaseModel):
    summary: str = ""
    stack: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    data_components: list[str] = Field(default_factory=list)
    deploy_units: list[str] = Field(default_factory=list)


class QualityPlan(BaseModel):
    unit_tests: list[str] = Field(default_factory=list)
    integration_tests: list[str] = Field(default_factory=list)
    e2e_tests: list[str] = Field(default_factory=list)
    static_checks: list[str] = Field(default_factory=list)
    security_checks: list[str] = Field(default_factory=list)


class DeploymentPlan(BaseModel):
    summary: str = ""
    artifacts: list[str] = Field(default_factory=list)
    ci_steps: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)


class MonitoringPlan(BaseModel):
    signals: list[str] = Field(default_factory=list)
    alert_rules: list[str] = Field(default_factory=list)
    maintenance_loops: list[str] = Field(default_factory=list)

class CapabilityRoute(BaseModel):
    request: str = ""
    selected: dict[str, Any] | None = None
    matches: list[dict[str, Any]] = Field(default_factory=list)


class TaskRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    prompt: str
    title: str | None = None
    repo_path: str | None = None
    project_id: str | None = None
    goal: str | None = None
    goal_id: str | None = None
    graph_id: str | None = None
    node_id: str | None = None
    scheduled_by: str | None = None
    auto_approve: bool = False
    context_mode: ContextMode = ContextMode.lean
    max_context_chars: int = 1600
    allow_resource_scan: bool = True
    allow_repo_status: bool = True
    capability_route: CapabilityRoute | None = None
    platform_context: dict[str, Any] = Field(default_factory=dict)
    vm_template: dict[str, Any] | None = None
    vm_context: dict[str, Any] = Field(default_factory=dict)
    execution_mode: ExecutionMode = ExecutionMode.governance
    preferred_worker: str | None = None
    scheduler_hint: dict[str, Any] = Field(default_factory=dict)
    context_package: dict[str, Any] = Field(default_factory=dict)
    tool_route: dict[str, Any] = Field(default_factory=dict)
    executor_route: dict[str, Any] = Field(default_factory=dict)
    executor_id: str | None = None
    execution_lane: str = 'host-control'
    worker_vm_policy: dict[str, Any] = Field(default_factory=dict)
    prompt_guard: dict[str, Any] = Field(default_factory=dict)
    tool_policy: dict[str, Any] = Field(default_factory=dict)
    security_review: dict[str, Any] = Field(default_factory=dict)
    artifact_spec: ArtifactSpec | None = None
    verification_contract: VerificationContract | None = None
    task_type: str | None = None
    queue_name: str | None = None
    verification_level: str | None = None
    max_runtime_seconds: int | None = None
    retry_limit: int | None = None
    rollback_rule: str | None = None
    parent_task_id: str | None = None
    root_task_id: str | None = None
    decomposition_depth: int = 0
    max_decomposition_depth: int = 2
    child_task_ids: list[str] = Field(default_factory=list)
    admission_lane: str | None = None
    admission_reason: str | None = None
    dependency_task_ids: list[str] = Field(default_factory=list)
    verification_signals: list[dict[str, Any]] = Field(default_factory=list)
    goal_admission: dict[str, Any] = Field(default_factory=dict)
    product_design: ProductDesign = Field(default_factory=ProductDesign)
    architecture_design: ArchitectureDesign = Field(default_factory=ArchitectureDesign)
    quality_plan: QualityPlan = Field(default_factory=QualityPlan)
    deployment_plan: DeploymentPlan = Field(default_factory=DeploymentPlan)
    monitoring_plan: MonitoringPlan = Field(default_factory=MonitoringPlan)
    contract: TaskContract = Field(default_factory=TaskContract)
    agent_assignments: list[AgentAssignment] = Field(default_factory=list)
    rule_checks: list[RuleCheck] = Field(default_factory=list)
    git_workflow: GitWorkflowState = Field(default_factory=GitWorkflowState)
    context_envelope: ContextEnvelope | None = None
    cheap_lane: CheapLaneState = Field(default_factory=CheapLaneState)
    escalation_count: int = 0
    status: TaskStatus = TaskStatus.queued
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    plan: list[StepSpec] = Field(default_factory=list)
    events: list[TaskEvent] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)

class PlannerResponse(BaseModel):
    summary: str
    steps: list[StepSpec]


class TaskDecompositionSpec(BaseModel):
    title: str
    prompt: str
    goal: str | None = None
    task_type: str | None = None
    path_kind: str | None = None
    queue_name: str | None = None
    verification_level: str | None = None
    preferred_worker: str | None = None
    execution_mode: ExecutionMode | None = None
    execution_lane: str | None = None
    decompose_children: bool = True
    shared_dependency_group: str | None = None
    repair_for: str | None = None
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    scheduler_hint: dict[str, Any] = Field(default_factory=dict)
    executor_hint: dict[str, Any] = Field(default_factory=dict)


class TaskDecompositionResponse(BaseModel):
    summary: str
    strategy: str = ""
    subtasks: list[TaskDecompositionSpec] = Field(default_factory=list)
    dag: dict[str, Any] = Field(default_factory=dict)


class DashboardStats(BaseModel):
    total_tasks: int
    active_tasks: int
    completed_tasks: int
    failed_tasks: int
    delivery_ready_tasks: int = 0
    released_tasks: int = 0
    verification_failed_tasks: int = 0


class ResourceRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:10])
    name: str
    kind: ResourceKind
    status: str = "available"
    location: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RepoRemote(BaseModel):
    name: str
    url: str
    provider: str


class RepoRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:10])
    name: str
    local_path: str
    default_branch: str = "main"
    remotes: list[RepoRemote] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    last_push_at: datetime | None = None


class RepoRegistration(BaseModel):
    name: str
    local_path: str
    default_branch: str = "main"
    github_url: str | None = None
    gitee_url: str | None = None


class RepoPushRequest(BaseModel):
    branch: str | None = None
    remote_names: list[str] | None = None
    set_upstream: bool = True


class RepoPushResult(BaseModel):
    repo_id: str
    branch: str
    pushed_remotes: list[str]
    output: str


class ProjectMemoryRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:10])
    name: str
    repo_id: str | None = None
    repo_path: str | None = None
    summary: str = ""
    project_goals: list[str] = Field(default_factory=list)
    technical_constraints: list[str] = Field(default_factory=list)
    architecture_decisions: list[str] = Field(default_factory=list)
    architecture_notes: list[str] = Field(default_factory=list)
    working_agreements: list[str] = Field(default_factory=list)
    recent_decisions: list[str] = Field(default_factory=list)
    preferred_context_mode: ContextMode = ContextMode.lean
    last_task_at: datetime | None = None


class ProjectMemoryUpsert(BaseModel):
    name: str
    repo_id: str | None = None
    repo_path: str | None = None
    summary: str = ""
    project_goals: list[str] = Field(default_factory=list)
    technical_constraints: list[str] = Field(default_factory=list)
    architecture_decisions: list[str] = Field(default_factory=list)
    architecture_notes: list[str] = Field(default_factory=list)
    working_agreements: list[str] = Field(default_factory=list)
    recent_decisions: list[str] = Field(default_factory=list)
    preferred_context_mode: ContextMode = ContextMode.lean


class PolicyRecord(BaseModel):
    version: str = "1"
    planner_role: str = "Use the premium planner only for decomposition, supervision, and escalation."
    cheap_lane_policy: str = "Push repetitive coding, review, summarization, and routine checks to cheap workers first."
    runtime_policy: str = "Prefer local runtime resources such as Git, Docker, virtual machines, and scripts before using expensive models."
    approval_policy: str = "High-risk execution stays gated; low-risk analysis and local checks can run automatically."
    development_test_loop: str = "For code work, follow a closed loop: inspect, edit, build, run local or VM tests, capture reports, then summarize failures or residual risk."
    failure_pause_policy: str = "If a long task fails or reaches diagnosis without further core instructions, pause execution, return a structured error report, and wait for explicit core guidance."
    self_improvement_policy: str = "Low-risk prompts, templates, tests, manifests, and docs may be improved automatically; security, permissions, and destructive boundaries may not."
    git_workflow_policy: str = "Code changes should prefer feature branches, local validation, commit summaries, and PR-ready outputs instead of direct main-branch edits."
    rule_engine_policy: str = "Changes touching auth, payments, database migrations, production deployment, or destructive commands must be gated and explained before execution."
    default_context_mode: ContextMode = ContextMode.lean
    default_max_context_chars: int = 1600











