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


class TaskDetail(TaskSummary):
    """Full task detail including dependencies and review history."""

    deps: list[str]
    reviews: list[Review]


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
