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
