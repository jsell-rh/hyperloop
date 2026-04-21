"""SPAWN phase -- decide what workers to spawn.

Returns SpawnPlan objects. Does NOT call runtime.spawn() or
state.transition_task(). Those are Orchestrator responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hyperloop.cycle.helpers import build_world, find_position_for_step
from hyperloop.domain.decide import decide
from hyperloop.domain.model import (
    AgentStep,
    Phase,
    PipelinePosition,
    SpawnWorker,
    TaskStatus,
    WorkerHandle,
)
from hyperloop.domain.pipeline import PipelineExecutor, SpawnAgent

if TYPE_CHECKING:
    from hyperloop.ports.runtime import Runtime
    from hyperloop.ports.state import StateStore


@dataclass(frozen=True)
class SpawnPlan:
    """A plan for a worker to be spawned by the Orchestrator."""

    task_id: str
    role: str
    position: PipelinePosition
    transition_phase: Phase | None
    transition_status: TaskStatus | None


def plan_spawns(
    state: StateStore,
    workers: dict[str, tuple[WorkerHandle, PipelinePosition, float]],
    executor: PipelineExecutor,
    runtime: Runtime,
    max_workers: int,
    max_task_rounds: int,
) -> list[SpawnPlan]:
    """Decide what to spawn and return spawn plans.

    Does NOT call runtime.spawn() or state.transition_task(). Returns
    SpawnPlan objects for the Orchestrator to execute.

    Args:
        state: State store for reading task state.
        workers: Current active workers.
        executor: Pipeline executor.
        runtime: Runtime for building world snapshot.
        max_workers: Maximum concurrent workers.
        max_task_rounds: Maximum rounds per task.

    Returns:
        List of SpawnPlan objects.
    """
    plans: list[SpawnPlan] = []

    world_after = build_world(workers, state, runtime)
    spawn_actions = decide(world_after, max_workers, max_task_rounds)

    for act in spawn_actions:
        if not isinstance(act, SpawnWorker):
            continue

        task = state.get_task(act.task_id)

        if act.role == "rebase-resolver":
            pos = executor.initial_position()
            plans.append(
                SpawnPlan(
                    task_id=act.task_id,
                    role="rebase-resolver",
                    position=pos,
                    transition_phase=Phase("rebase-resolver"),
                    transition_status=TaskStatus.IN_PROGRESS,
                )
            )
        elif task.status == TaskStatus.IN_PROGRESS and task.phase is not None:
            # Only spawn for agent steps -- gates/actions handled in ADVANCE
            phase_name = str(task.phase)
            pos = find_position_for_step(executor, phase_name)
            if pos is not None:
                step = PipelineExecutor.resolve_step(executor.pipeline, pos.path)
                if isinstance(step, AgentStep):
                    plans.append(
                        SpawnPlan(
                            task_id=act.task_id,
                            role=phase_name,
                            position=pos,
                            transition_phase=None,
                            transition_status=None,
                        )
                    )
        else:
            pos = executor.initial_position()
            pipe_action, pos = executor.next_action(pos, result=None)
            if isinstance(pipe_action, SpawnAgent):
                plans.append(
                    SpawnPlan(
                        task_id=act.task_id,
                        role=pipe_action.agent,
                        position=pos,
                        transition_phase=Phase(pipe_action.agent),
                        transition_status=TaskStatus.IN_PROGRESS,
                    )
                )

    return plans
