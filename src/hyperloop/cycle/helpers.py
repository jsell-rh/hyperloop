"""Pure helpers for the orchestrator cycle.

All functions are stateless and side-effect free.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hyperloop.domain.model import (
    PhaseMap,
    WorkerState,
    World,
)
from hyperloop.domain.task_processor import determine_step_type, extract_role

if TYPE_CHECKING:
    from collections.abc import Mapping

    from hyperloop.ports.runtime import Runtime, WorkerPollStatus
    from hyperloop.ports.state import StateStore

BRANCH_PREFIX = "hyperloop"


def extract_roles_from_phases(phases: PhaseMap) -> set[str]:
    """Extract agent role names from a phase map."""
    roles: set[str] = set()
    for phase in phases.values():
        step_type = determine_step_type(phase)
        if step_type == "agent":
            roles.add(extract_role(phase))
    return roles


def extract_step_names(phases: PhaseMap) -> set[str]:
    """Extract action/check/signal step names from a phase map."""
    names: set[str] = set()
    for phase in phases.values():
        step_type = determine_step_type(phase)
        if step_type in ("action", "check", "signal"):
            names.add(extract_role(phase))
    return names


def build_world(
    workers: Mapping[str, tuple[object, float]],
    state: StateStore,
    runtime: Runtime,
) -> World:
    """Build a World snapshot including current worker state from runtime.

    Args:
        workers: Active worker tracking dict: task_id -> (handle, spawn_time).
        state: State store to get base world from.
        runtime: Runtime to poll worker status.

    Returns:
        A World snapshot with task and worker state.
    """
    from hyperloop.domain.model import WorkerHandle

    base_world = state.get_world()
    worker_states: dict[str, WorkerState] = {}
    for task_id, (handle, _spawn_time) in workers.items():
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
