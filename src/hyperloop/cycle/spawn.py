"""SPAWN phase -- decide what workers to spawn.

Returns SpawnPlan objects. Does NOT call runtime.spawn() or
state.transition_task(). Those are Orchestrator responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hyperloop.cycle.helpers import build_world
from hyperloop.domain.decide import decide
from hyperloop.domain.model import (
    Halt,
    Phase,
    SpawnWorker,
    TaskStatus,
    WorkerHandle,
)
from hyperloop.domain.task_processor import (
    determine_step_type,
    extract_role,
    first_phase,
)

if TYPE_CHECKING:
    from hyperloop.domain.model import PhaseMap
    from hyperloop.ports.runtime import Runtime
    from hyperloop.ports.state import StateStore


@dataclass(frozen=True)
class SpawnPlan:
    """A plan for a worker to be spawned by the Orchestrator."""

    task_id: str
    role: str
    transition_phase: Phase | None
    transition_status: TaskStatus | None


@dataclass(frozen=True)
class SpawnResult:
    """Result of the SPAWN planning phase."""

    plans: list[SpawnPlan]
    halt_reason: str | None


def plan_spawns(
    state: StateStore,
    workers: dict[str, tuple[WorkerHandle, float]],
    phases: PhaseMap,
    runtime: Runtime,
    max_workers: int,
    max_task_rounds: int,
) -> SpawnResult:
    """Decide what to spawn and return spawn plans.

    Does NOT call runtime.spawn() or state.transition_task(). Returns
    SpawnResult with plans and optional halt reason.

    Args:
        state: State store for reading task state.
        workers: Current active workers: task_id -> (handle, spawn_time).
        phases: Flat phase map from the process.
        runtime: Runtime for building world snapshot.
        max_workers: Maximum concurrent workers.
        max_task_rounds: Maximum rounds per task.

    Returns:
        SpawnResult with plans and optional halt reason.
    """
    plans: list[SpawnPlan] = []
    halt_reason: str | None = None

    world_after = build_world(workers, state, runtime)
    spawn_actions = decide(world_after, max_workers, max_task_rounds)

    for act in spawn_actions:
        if isinstance(act, Halt):
            halt_reason = act.reason
            continue

        if not isinstance(act, SpawnWorker):
            continue

        task = state.get_task(act.task_id)

        if task.status == TaskStatus.NOT_STARTED:
            # First spawn: set phase to first phase, status to IN_PROGRESS
            phase_name = first_phase(phases)
            phase_step = phases[phase_name]
            step_type = determine_step_type(phase_step)
            if step_type == "agent":
                role = extract_role(phase_step)
                plans.append(
                    SpawnPlan(
                        task_id=act.task_id,
                        role=role,
                        transition_phase=Phase(phase_name),
                        transition_status=TaskStatus.IN_PROGRESS,
                    )
                )
        elif task.status == TaskStatus.IN_PROGRESS and task.phase is not None:
            # Resume: get current phase and extract role
            phase_name = str(task.phase)
            if phase_name not in phases:
                continue
            phase_step = phases[phase_name]
            step_type = determine_step_type(phase_step)
            if step_type == "agent":
                role = extract_role(phase_step)
                plans.append(
                    SpawnPlan(
                        task_id=act.task_id,
                        role=role,
                        transition_phase=None,
                        transition_status=None,
                    )
                )

    return SpawnResult(plans=plans, halt_reason=halt_reason)
