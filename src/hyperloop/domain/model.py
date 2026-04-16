"""Domain model — value objects, entities, and pipeline primitives.

All types are pure data with no I/O dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, NewType

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskStatus(Enum):
    """Lifecycle status of a task."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    NEEDS_REBASE = "needs_rebase"
    COMPLETE = "complete"
    FAILED = "failed"


class Verdict(Enum):
    """Outcome reported by a worker."""

    PASS = "pass"
    FAIL = "fail"
    TIMEOUT = "timeout"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Simple types
# ---------------------------------------------------------------------------

Phase = NewType("Phase", str)
"""Current pipeline step name — a branded string for type safety."""

# ---------------------------------------------------------------------------
# Core entities / value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    """A unit of work tracked by the orchestrator."""

    id: str
    title: str
    spec_ref: str
    status: TaskStatus
    phase: Phase | None
    deps: tuple[str, ...]
    round: int
    branch: str | None
    pr: str | None


@dataclass(frozen=True)
class WorkerResult:
    """Verdict reported by a finished worker."""

    verdict: Verdict
    findings: int
    detail: str


@dataclass(frozen=True)
class WorkerHandle:
    """Opaque handle to a running worker session."""

    task_id: str
    role: str
    agent_id: str
    session_id: str | None


# ---------------------------------------------------------------------------
# Pipeline primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleStep:
    """Spawn an agent with a given role."""

    role: str
    on_pass: str | None
    on_fail: str | None


@dataclass(frozen=True)
class GateStep:
    """Block until an external signal is received."""

    gate: str


@dataclass(frozen=True)
class LoopStep:
    """Wrap steps — on fail retry from top, on pass continue."""

    steps: tuple[PipelineStep, ...]


@dataclass(frozen=True)
class ActionStep:
    """Terminal operation (merge-pr, mark-pr-ready, etc.)."""

    action: str


PipelineStep = RoleStep | GateStep | LoopStep | ActionStep
"""Union of all pipeline primitive types."""


@dataclass(frozen=True)
class PipelinePosition:
    """Path through a nested pipeline structure.

    Each element in `path` is an index into a list of steps at that nesting level.
    Example: path=[0, 1] means "first step in pipeline (a LoopStep), second step within
    that loop."
    """

    path: tuple[int, ...]


@dataclass(frozen=True)
class Process:
    """A named process with intake and per-task pipelines."""

    name: str
    intake: tuple[PipelineStep, ...]
    pipeline: tuple[PipelineStep, ...]


# ---------------------------------------------------------------------------
# World snapshot (input to the decide function)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkerState:
    """Snapshot of a worker's current status."""

    task_id: str
    role: str
    status: Literal["running", "done", "failed"]


@dataclass(frozen=True)
class World:
    """Complete snapshot of orchestrator state — input to decide()."""

    tasks: dict[str, Task]
    workers: dict[str, WorkerState]
    epoch: str


# ---------------------------------------------------------------------------
# Actions (output of the decide function)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpawnWorker:
    """Spawn a new worker for a task with a given role."""

    task_id: str
    role: str


@dataclass(frozen=True)
class ReapWorker:
    """Collect results from a finished worker."""

    task_id: str


@dataclass(frozen=True)
class AdvanceTask:
    """Transition a task to a new status and/or phase."""

    task_id: str
    to_status: TaskStatus
    to_phase: Phase | None


@dataclass(frozen=True)
class RunPM:
    """Run the PM intake process."""


@dataclass(frozen=True)
class RunProcessImprover:
    """Run the process improver with accumulated findings."""

    findings: dict[str, int]


@dataclass(frozen=True)
class MergePR:
    """Squash-merge a task's PR."""

    task_id: str


@dataclass(frozen=True)
class Halt:
    """Stop the orchestrator loop."""

    reason: str


Action = SpawnWorker | ReapWorker | AdvanceTask | RunPM | RunProcessImprover | MergePR | Halt
"""Union of all action types emitted by the decide function."""


# ---------------------------------------------------------------------------
# Prompt composition context types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskContext:
    """Context for per-task workers (implementer, verifier, rebase-resolver)."""

    task_id: str
    spec_ref: str
    findings: str
    round: int


@dataclass(frozen=True)
class IntakeContext:
    """Context for PM intake."""

    unprocessed_specs: tuple[str, ...]


@dataclass(frozen=True)
class ImprovementContext:
    """Context for process-improver."""

    findings: str


AgentContext = TaskContext | IntakeContext | ImprovementContext
"""Union of all context types for prompt composition."""
