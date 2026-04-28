"""Pydantic response models for the dashboard API."""

from __future__ import annotations

from pydantic import BaseModel


class TaskSummary(BaseModel):
    """Summary representation of a task."""

    id: str
    title: str
    status: str
    phase: str | None
    round: int
    branch: str | None
    pr: str | None
    spec_ref: str
    pr_title: str | None = None
    pr_description: str | None = None


class Review(BaseModel):
    """A single review entry from a task round."""

    round: int
    role: str
    verdict: str
    detail: str


class DepDetail(BaseModel):
    """Summary info for a dependency task."""

    id: str
    title: str
    status: str


class TaskDetail(TaskSummary):
    """Full task detail including dependencies and review history."""

    deps: list[str]
    deps_detail: list[DepDetail]
    reviews: list[Review]


class PipelineStepInfo(BaseModel):
    """A single step in the flattened pipeline."""

    name: str
    type: str


class PromptSectionResponse(BaseModel):
    """A section of a reconstructed prompt with source provenance."""

    source: str
    label: str
    content: str


class ReconstructedPrompt(BaseModel):
    """A reconstructed prompt for a task role."""

    role: str
    sections: list[PromptSectionResponse]


class SpecSummary(BaseModel):
    """Spec with aggregated task progress counts and sync metadata."""

    spec_ref: str
    title: str
    tasks_total: int
    tasks_complete: int
    tasks_in_progress: int
    tasks_failed: int
    tasks_not_started: int
    drift_type: str | None = None
    drift_detail: str = ""
    stage: str = "written"
    last_audit_result: str | None = None
    last_audit: str | None = None
    current_sha: str | None = None
    pinned_sha: str | None = None


class SpecDriftDetail(BaseModel):
    """Detailed drift info for a single spec."""

    spec_ref: str
    drift_type: str | None
    drift_detail: str
    old_sha: str | None
    new_sha: str | None
    old_content: str | None
    new_content: str | None


class SpecDetail(BaseModel):
    """Spec content with associated tasks."""

    spec_ref: str
    content: str
    tasks: list[TaskSummary]


class SummaryResponse(BaseModel):
    """Aggregate progress across all tasks."""

    total: int
    not_started: int
    in_progress: int
    complete: int
    failed: int
    specs_total: int
    specs_complete: int


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    repo_path: str
    state_store: str
    spec_source: str


# ---------------------------------------------------------------------------
# Graph models
# ---------------------------------------------------------------------------


class GraphNode(BaseModel):
    """A task node in the dependency graph."""

    id: str
    title: str
    status: str
    phase: str | None
    spec_ref: str
    round: int


class GraphEdge(BaseModel):
    """A directed edge in the dependency graph."""

    from_id: str
    to_id: str


class GraphResponse(BaseModel):
    """Full dependency graph with critical path."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    critical_path: list[str]


# ---------------------------------------------------------------------------
# Process models
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Activity models
# ---------------------------------------------------------------------------


class ActiveWorker(BaseModel):
    """A currently running worker."""

    task_id: str
    role: str
    started_at: str
    duration_s: float


class ReapedWorker(BaseModel):
    """A worker that completed in a cycle."""

    task_id: str
    role: str
    verdict: str
    duration_s: float


class CollectPhase(BaseModel):
    """COLLECT phase detail for a cycle."""

    reaped: list[ReapedWorker]


class IntakePhase(BaseModel):
    """INTAKE phase detail for a cycle."""

    ran: bool
    created_tasks: int | None = None


class PhaseTransition(BaseModel):
    """A task phase transition in the ADVANCE phase."""

    task_id: str
    from_phase: str | None
    to_phase: str | None


class AdvancePhase(BaseModel):
    """ADVANCE phase detail for a cycle."""

    transitions: list[PhaseTransition]


class SpawnedWorker(BaseModel):
    """A worker spawned in a cycle."""

    task_id: str
    role: str


class SpawnPhase(BaseModel):
    """SPAWN phase detail for a cycle."""

    spawned: list[SpawnedWorker]


class CyclePhases(BaseModel):
    """The four phases of a reconciliation cycle."""

    collect: CollectPhase
    intake: IntakePhase
    advance: AdvancePhase
    spawn: SpawnPhase


class AuditDetail(BaseModel):
    """Detail for a single audit run within a reconcile phase."""

    spec_ref: str
    result: str
    duration_s: float


class ReconcileDetail(BaseModel):
    """Detail for the reconcile phase within a cycle."""

    drift_count: int
    audits: list[AuditDetail]
    gc_pruned: int
    reconcile_duration_s: float | None
    intake_ran: bool = False
    intake_created_tasks: int | None = None
    intake_duration_s: float | None = None
    process_improver_ran: bool = False
    process_improver_duration_s: float | None = None


class AuditEntry(BaseModel):
    """A single auditor execution with timing for the Gantt chart."""

    spec_ref: str
    result: str
    started_at: str
    duration_s: float


class AuditTimeline(BaseModel):
    """Timeline of parallel auditor executions for a cycle."""

    entries: list[AuditEntry]
    total_duration_s: float
    max_parallelism: int


class CyclePhaseTiming(BaseModel):
    """Per-phase duration breakdown for a cycle."""

    collect_s: float | None = None
    reconcile_s: float | None = None
    advance_s: float | None = None
    spawn_s: float | None = None


class CycleDetail(BaseModel):
    """Detail for a single reconciliation cycle."""

    cycle: int
    timestamp: str
    duration_s: float | None
    phases: CyclePhases
    reconcile: ReconcileDetail | None = None
    audit_timeline: AuditTimeline | None = None
    phase_timing: CyclePhaseTiming | None = None


class WorkerHistoryEntry(BaseModel):
    """A worker execution in a task's history."""

    role: str
    round: int
    started_at: str
    duration_s: float
    verdict: str | None


class TaskInFlight(BaseModel):
    """An in-progress task with its worker journey."""

    task_id: str
    title: str
    status: str
    phase: str | None
    round: int
    spec_ref: str
    current_worker: ActiveWorker | None
    worker_history: list[WorkerHistoryEntry]


class FlatEvent(BaseModel):
    """A single non-empty event extracted from a cycle."""

    timestamp: str
    cycle: int
    event_type: str
    task_id: str | None
    detail: str
    verdict: str | None
    duration_s: float | None


class ActivityResponse(BaseModel):
    """Response for the activity endpoint."""

    current_cycle: int
    orchestrator_status: str
    active_workers: list[ActiveWorker]
    cycles: list[CycleDetail]
    enabled: bool
    tasks_in_flight: list[TaskInFlight]
    flattened_events: list[FlatEvent]


class WorkerHeartbeat(BaseModel):
    """Per-worker heartbeat data from recent worker_message events."""

    task_id: str
    role: str
    last_message_at: str
    last_message_type: str
    last_tool_name: str | None
    message_count_since: int
    seconds_since_last: float


class HeartbeatResponse(BaseModel):
    """Response for the worker heartbeat endpoint."""

    heartbeats: list[WorkerHeartbeat]
    server_time: str


class PipelineTreeStep(BaseModel):
    """A step in the pipeline tree (preserving nesting). Legacy."""

    type: str
    name: str | None = None
    children: list[PipelineTreeStep] | None = None


class PhaseDefinition(BaseModel):
    """A single phase in the flat phase map."""

    run: str
    on_pass: str
    on_fail: str
    on_wait: str | None = None


class ProcessLearning(BaseModel):
    """Process-improver learning state."""

    patched_agents: list[str]
    guidelines: dict[str, str]


class ProcessResponse(BaseModel):
    """Full process definition with learning state."""

    phases: dict[str, PhaseDefinition]
    phase_order: list[str]
    pipeline_raw: str
    gates: dict[str, object]
    actions: dict[str, object]
    hooks: dict[str, object]
    process_learning: ProcessLearning
    source_file: str
    base_ref: str | None


# ---------------------------------------------------------------------------
# Agents models
# ---------------------------------------------------------------------------


class AgentRosterEntry(BaseModel):
    """Per-role performance metrics computed from FileProbe events."""

    role: str
    success_rate: float | None
    avg_duration_s: float | None
    total_executions: int
    failure_patterns: list[str]


class AgentDefinition(BaseModel):
    """Per-role agent definition with layer breakdown."""

    name: str
    prompt: str
    guidelines: str
    has_process_patches: bool
    process_overlay_guidelines: str | None
    process_overlay_file: str | None


class CheckScript(BaseModel):
    """An executable check script from .hyperloop/checks/."""

    name: str
    path: str
    content: str


# ---------------------------------------------------------------------------
# Control operation request models
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Trend metrics models
# ---------------------------------------------------------------------------


class ConvergenceTrendPoint(BaseModel):
    """Per-cycle convergence count."""

    cycle: int
    converged_count: int


class ThroughputPoint(BaseModel):
    """Tasks completed/failed per cycle."""

    cycle: int
    completed: int
    failed: int


class TrendMetrics(BaseModel):
    """Aggregated metrics over the last N cycles."""

    cycles_analyzed: int
    convergence_trend: list[ConvergenceTrendPoint]
    task_throughput: list[ThroughputPoint]
    avg_worker_duration_s: float | None
    total_tasks_completed: int
    total_tasks_failed: int


# ---------------------------------------------------------------------------
# KPI / Visualization models
# ---------------------------------------------------------------------------


class SparklinePoint(BaseModel):
    """A single value in a sparkline series."""

    cycle: int
    value: float


class KpiCard(BaseModel):
    """A single KPI card with sparkline and trend."""

    label: str
    value: float
    unit: str
    sparkline: list[SparklinePoint]
    trend: str  # "up", "down", "flat"
    trend_is_good: bool


class KpiResponse(BaseModel):
    """All 6 KPI cards."""

    cards: list[KpiCard]


class BurndownPoint(BaseModel):
    """A single point in the burndown/burnup chart."""

    cycle: int
    timestamp: str
    burnup: int
    burndown: int
    scope_change: bool


class BurndownResponse(BaseModel):
    """Time series data for burndown/burnup chart."""

    points: list[BurndownPoint]


class VelocityPoint(BaseModel):
    """A single velocity data point."""

    cycle: int
    timestamp: str
    tasks_per_hour: float
    completed_count: int


class VelocityResponse(BaseModel):
    """Velocity data points over time."""

    points: list[VelocityPoint]


class RoundEfficiencyPoint(BaseModel):
    """Average rounds per time window."""

    window_start: int
    window_end: int
    avg_rounds: float
    sample_count: int


class RoundDistributionBucket(BaseModel):
    """Count of tasks completing in N rounds."""

    rounds: str  # "1", "2", "3", "4", "5+"
    count: int


class RoundEfficiencyResponse(BaseModel):
    """Round efficiency trend and distribution."""

    trend: list[RoundEfficiencyPoint]
    distribution: list[RoundDistributionBucket]


class PhaseFunnelEntry(BaseModel):
    """Per-phase stats for the funnel visualization."""

    phase: str
    avg_duration_s: float
    total_executions: int
    first_pass_success_rate: float


class PhaseFunnelResponse(BaseModel):
    """Phase funnel data."""

    phases: list[PhaseFunnelEntry]


class RestartRequest(BaseModel):
    """Request body for restarting a task."""

    expected_round: int


class RetireRequest(BaseModel):
    """Request body for retiring a task."""

    expected_round: int


class ForceClearRequest(BaseModel):
    """Request body for force-clearing a task past a signal step."""

    expected_round: int
