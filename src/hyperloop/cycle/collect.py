"""COLLECT phase -- reap finished workers.

Pure decision-maker: takes worker state, polls runtime, returns what was
reaped and what remains. Does NOT mutate the workers dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hyperloop.domain.decide import decide
from hyperloop.domain.model import (
    ReapWorker,
    WorkerHandle,
    WorkerPollStatus,
)

if TYPE_CHECKING:
    from hyperloop.domain.model import WorkerResult
    from hyperloop.ports.probe import OrchestratorProbe
    from hyperloop.ports.runtime import Runtime
    from hyperloop.ports.state import StateStore

from hyperloop.cycle.helpers import build_world


@dataclass(frozen=True)
class CollectResult:
    """Result of the COLLECT phase."""

    reaped: dict[str, WorkerResult]
    reaped_metadata: dict[str, tuple[WorkerHandle, float]]
    remaining_workers: dict[str, tuple[WorkerHandle, float]]
    crashed_task_ids: frozenset[str] = frozenset()


def collect(
    workers: dict[str, tuple[WorkerHandle, float]],
    state: StateStore,
    runtime: Runtime,
    probe: OrchestratorProbe,
    max_workers: int,
    max_task_rounds: int,
    cycle: int,
) -> CollectResult:
    """Reap finished workers. Returns CollectResult.

    Does NOT mutate the ``workers`` dict. Instead, returns remaining workers
    and reaped metadata as separate fields.

    Args:
        workers: Current active workers: task_id -> (handle, spawn_time).
        state: State store for building world snapshot.
        runtime: Runtime for polling and reaping workers.
        probe: Probe for observability events.
        max_workers: Maximum concurrent workers.
        max_task_rounds: Maximum rounds per task.
        cycle: Current cycle number.

    Returns:
        CollectResult with reaped results, metadata, and remaining workers.
    """
    world = build_world(workers, state, runtime)
    actions = decide(world, max_workers, max_task_rounds)

    reaped_results: dict[str, WorkerResult] = {}
    reaped_metadata: dict[str, tuple[WorkerHandle, float]] = {}
    remaining: dict[str, tuple[WorkerHandle, float]] = dict(workers)
    crashed: set[str] = set()

    # Identify workers whose poll status was FAILED (crashed)
    failed_poll_ids = {
        ws.task_id for ws in world.workers.values() if ws.status == WorkerPollStatus.FAILED
    }

    for act in actions:
        if isinstance(act, ReapWorker):
            task_id = act.task_id
            if task_id in remaining:
                handle, spawn_time = remaining[task_id]
                result = runtime.reap(handle)
                reaped_results[task_id] = result
                reaped_metadata[task_id] = (handle, spawn_time)
                del remaining[task_id]
                if task_id in failed_poll_ids:
                    crashed.add(task_id)

    return CollectResult(
        reaped=reaped_results,
        reaped_metadata=reaped_metadata,
        remaining_workers=remaining,
        crashed_task_ids=frozenset(crashed),
    )
