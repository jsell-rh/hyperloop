"""Pure pipeline navigation helpers.

All functions are stateless and side-effect free.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hyperloop.domain.model import (
    ActionStep,
    AgentStep,
    CheckStep,
    GateStep,
    LoopStep,
    PipelinePosition,
    WorkerState,
    World,
)
from hyperloop.domain.pipeline import (
    PerformAction,
    PerformCheck,
    PipelineAction,
    SpawnAgent,
    WaitForGate,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from hyperloop.domain.model import PipelineStep, Task
    from hyperloop.domain.pipeline import PipelineExecutor
    from hyperloop.ports.runtime import Runtime, WorkerPollStatus
    from hyperloop.ports.state import StateStore

BRANCH_PREFIX = "hyperloop"


def find_position_for_role(executor: PipelineExecutor, role: str) -> PipelinePosition | None:
    """Walk the pipeline for an AgentStep matching the given role name."""

    def _search(
        steps: tuple[PipelineStep, ...], prefix: tuple[int, ...]
    ) -> PipelinePosition | None:
        for i, step in enumerate(steps):
            path = (*prefix, i)
            if isinstance(step, AgentStep) and step.agent == role:
                return PipelinePosition(path=path)
            if isinstance(step, LoopStep):
                found = _search(step.steps, path)
                if found is not None:
                    return found
        return None

    return _search(executor.pipeline, ())


def find_position_for_step(executor: PipelineExecutor, phase_name: str) -> PipelinePosition | None:
    """Walk the pipeline for any step whose name matches phase_name."""

    def _step_name(step: PipelineStep) -> str | None:
        if isinstance(step, AgentStep):
            return step.agent
        if isinstance(step, GateStep):
            return step.gate
        if isinstance(step, CheckStep):
            return step.check
        if isinstance(step, ActionStep):
            return step.action
        return None

    def _search(
        steps: tuple[PipelineStep, ...], prefix: tuple[int, ...]
    ) -> PipelinePosition | None:
        for i, step in enumerate(steps):
            path = (*prefix, i)
            if _step_name(step) == phase_name:
                return PipelinePosition(path=path)
            if isinstance(step, LoopStep):
                found = _search(step.steps, path)
                if found is not None:
                    return found
        return None

    return _search(executor.pipeline, ())


def position_from_phase(executor: PipelineExecutor, task: Task) -> PipelinePosition:
    """Determine pipeline position from a task's current phase."""
    if task.phase is not None:
        pos = find_position_for_role(executor, str(task.phase))
        if pos is not None:
            return pos
    return executor.initial_position()


def phase_for_action(action: object) -> str | None:
    """Extract a phase name from a pipeline action (WaitForGate, PerformCheck, or PerformAction)."""
    if isinstance(action, WaitForGate):
        return action.gate
    if isinstance(action, PerformCheck):
        return action.check
    if isinstance(action, PerformAction):
        return action.action
    return None


def phase_for_pipe_action(
    action: PipelineAction,
) -> str | None:
    """Extract a phase name from any pipeline action type."""
    if isinstance(action, SpawnAgent):
        return action.agent
    if isinstance(action, WaitForGate):
        return action.gate
    if isinstance(action, PerformCheck):
        return action.check
    if isinstance(action, PerformAction):
        return action.action
    return None


def collect_roles(steps: tuple[PipelineStep, ...]) -> set[str]:
    """Recursively collect all role names from a pipeline."""
    roles: set[str] = set()
    for step in steps:
        if isinstance(step, AgentStep):
            roles.add(step.agent)
        elif isinstance(step, LoopStep):
            roles.update(collect_roles(step.steps))
        if isinstance(step, CheckStep) and step.agent is not None:
            roles.add(step.agent)
    return roles


def collect_steps_of_type(steps: tuple[PipelineStep, ...], step_type: type) -> list[PipelineStep]:
    """Recursively collect all steps of a given type from a pipeline."""
    result: list[PipelineStep] = []
    for step in steps:
        if isinstance(step, step_type):
            result.append(step)
        elif isinstance(step, LoopStep):
            result.extend(collect_steps_of_type(step.steps, step_type))
    return result


def build_world(
    workers: Mapping[str, tuple[object, PipelinePosition, float]],
    state: StateStore,
    runtime: Runtime,
) -> World:
    """Build a World snapshot including current worker state from runtime.

    Args:
        workers: Active worker tracking dict: task_id -> (handle, position, spawn_time).
        state: State store to get base world from.
        runtime: Runtime to poll worker status.

    Returns:
        A World snapshot with task and worker state.
    """
    from hyperloop.domain.model import WorkerHandle

    base_world = state.get_world()
    worker_states: dict[str, WorkerState] = {}
    for task_id, (handle, _pos, _spawn_time) in workers.items():
        assert isinstance(handle, WorkerHandle)
        poll_status: WorkerPollStatus = runtime.poll(handle)
        worker_states[task_id] = WorkerState(
            task_id=task_id,
            role=handle.role,
            status=poll_status,
        )
    return World(
        tasks=base_world.tasks,
        workers=worker_states,
        epoch=base_world.epoch,
    )
