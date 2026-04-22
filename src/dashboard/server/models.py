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
    """Spec with aggregated task progress counts."""

    spec_ref: str
    title: str
    tasks_total: int
    tasks_complete: int
    tasks_in_progress: int
    tasks_failed: int
    tasks_not_started: int


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


class CycleDetail(BaseModel):
    """Detail for a single reconciliation cycle."""

    cycle: int
    timestamp: str
    duration_s: float | None
    phases: CyclePhases


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


class PipelineTreeStep(BaseModel):
    """A step in the pipeline tree (preserving nesting)."""

    type: str
    name: str | None = None
    children: list[PipelineTreeStep] | None = None


class ProcessLearning(BaseModel):
    """Process-improver learning state."""

    patched_agents: list[str]
    guidelines: dict[str, str]


class ProcessResponse(BaseModel):
    """Full process definition with learning state."""

    pipeline_steps: list[PipelineTreeStep]
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
