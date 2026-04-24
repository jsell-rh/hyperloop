"""Domain model — value objects, entities, and pipeline primitives.

All types are pure data with no I/O dependencies.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, NewType

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskStatus(Enum):
    """Lifecycle status of a task."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"  # kept for backward compatibility
    COMPLETED = "completed"
    FAILED = "failed"


class Verdict(Enum):
    """Outcome reported by a worker."""

    PASS = "pass"
    FAIL = "fail"


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
    pr_title: str | None = None
    pr_description: str | None = None


@dataclass(frozen=True)
class WorkerResult:
    """Verdict reported by a finished worker."""

    verdict: Verdict
    detail: str


@dataclass(frozen=True)
class WorkerHandle:
    """Opaque handle to a running worker session."""

    task_id: str
    role: str
    agent_id: str
    session_id: str | None


@dataclass(frozen=True)
class TaskProposal:
    """Value object produced by the PM agent during intake."""

    title: str
    spec_ref: str  # "specs/widget.md@abc123"
    deps: tuple[str, ...]
    pr_title: str | None = None
    pr_description: str | None = None


# ---------------------------------------------------------------------------
# Reconciler types — flat phase map replacing nested pipelines
# ---------------------------------------------------------------------------


class StepOutcome(Enum):
    """Result category from executing a phase step."""

    ADVANCE = "advance"
    RETRY = "retry"
    WAIT = "wait"


@dataclass(frozen=True)
class StepResult:
    """Value object returned by step execution."""

    outcome: StepOutcome
    detail: str
    pr_url: str | None = None


class SignalStatus(Enum):
    """Status of an external signal (gate replacement)."""

    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"


@dataclass(frozen=True)
class Signal:
    """Value object returned by signal checks."""

    status: SignalStatus
    message: str


@dataclass(frozen=True)
class PhaseStep:
    """A single step in a flat phase map."""

    run: str
    on_pass: str
    on_fail: str
    on_wait: str | None = None
    args: dict[str, object] = field(default_factory=dict)


PhaseMap = dict[str, PhaseStep]
"""Flat mapping of phase name to step definition."""


# ---------------------------------------------------------------------------
# Pipeline primitives (legacy — kept for backward compatibility)
# ---------------------------------------------------------------------------


def _empty_args() -> dict[str, object]:
    return {}


@dataclass(frozen=True)
class AgentStep:
    """Spawn an agent with a given role."""

    agent: str
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
class CheckStep:
    """Evaluation step — mechanical or agent-backed.

    On PASS, advance. On FAIL, enclosing loop restarts. On WAIT, stay and
    re-evaluate next cycle.

    When ``agent`` is set, the framework spawns that agent role for evaluation
    after the check adapter's pre-conditions return PASS.
    """

    check: str
    args: dict[str, object] = dataclasses.field(default_factory=_empty_args)
    agent: str | None = None


@dataclass(frozen=True)
class ActionStep:
    """Execute an operation (merge-pr, mark-pr-ready, post-pr-comment, etc.)."""

    action: str
    args: dict[str, object] = dataclasses.field(default_factory=_empty_args)


PipelineStep = AgentStep | GateStep | LoopStep | CheckStep | ActionStep
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
    """A named process with a per-task pipeline.

    Supports both the legacy nested pipeline and the new flat phase map.
    New code should use ``phases``; ``pipeline`` is kept for backward
    compatibility during the migration.
    """

    name: str
    pipeline: tuple[PipelineStep, ...] = ()
    phases: PhaseMap = field(default_factory=dict)


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
class Halt:
    """Stop the orchestrator loop."""

    reason: str


Action = SpawnWorker | ReapWorker | AdvanceTask | Halt
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
    pr_feedback: str = ""


@dataclass(frozen=True)
class SpecIntakeEntry:
    """A spec that needs PM attention, with optional change context."""

    path: str
    change_type: str  # "new" or "modified"
    diff: str = ""


@dataclass(frozen=True)
class IntakeContext:
    """Context for PM intake."""

    unprocessed_specs: tuple[str, ...]
    spec_entries: tuple[SpecIntakeEntry, ...] = ()
    failed_tasks: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImprovementContext:
    """Context for process-improver."""

    findings: str


AgentContext = TaskContext | IntakeContext | ImprovementContext
"""Union of all context types for prompt composition."""


# ---------------------------------------------------------------------------
# Composed prompt with provenance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromptSection:
    """A section of a composed prompt with its source layer."""

    source: str  # "base", "project-overlay", "process-overlay", "spec", "findings", "runtime"
    label: str  # "prompt", "guidelines", "spec", "findings", "epilogue"
    content: str


@dataclass(frozen=True)
class ComposedPrompt:
    """A fully composed prompt with provenance for each section."""

    sections: tuple[PromptSection, ...]
    text: str  # the flattened string passed to the runtime
