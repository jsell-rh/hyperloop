"""Decision function — given a World snapshot, return a list of Actions.

This is the orchestrator's brain: a pure function with no I/O dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from k_orchestrate.domain.model import (
    AdvanceTask,
    Halt,
    ReapWorker,
    SpawnWorker,
    TaskStatus,
)

if TYPE_CHECKING:
    from k_orchestrate.domain.model import Action, Task, World


def _deps_met(task: Task, tasks: dict[str, Task]) -> bool:
    """Check if all dependencies of a task are complete."""
    for dep_id in task.deps:
        dep = tasks.get(dep_id)
        if dep is None or dep.status != TaskStatus.COMPLETE:
            return False
    return True


def _task_has_worker(task_id: str, world: World) -> bool:
    """Check if a task has any worker (running, done, or failed).

    Tasks with a worker in any state should not be re-spawned: running workers
    are active, done/failed workers are about to be reaped by the loop.
    """
    return any(ws.task_id == task_id for ws in world.workers.values())


def decide(world: World, max_workers: int, max_rounds: int) -> list[Action]:
    """Decide what actions to take given the current world state.

    Returns an ordered list of actions: reaps first, then advances, then spawns,
    then halt if applicable.
    """
    actions: list[Action] = []

    # ---- 1. Reap finished workers (status == "done" or "failed") -----------
    for ws in world.workers.values():
        if ws.status in ("done", "failed"):
            actions.append(ReapWorker(task_id=ws.task_id))

    # ---- 2. Check for tasks that hit max_rounds → AdvanceTask + Halt ------
    for task in world.tasks.values():
        if task.status == TaskStatus.IN_PROGRESS and task.round >= max_rounds:
            actions.append(AdvanceTask(task_id=task.id, to_status=TaskStatus.FAILED, to_phase=None))
            actions.append(Halt(reason=f"task {task.id} exceeded max_rounds ({max_rounds})"))
            return actions

    # ---- 3. Count active (running) workers ---------------------------------
    active_count = sum(1 for ws in world.workers.values() if ws.status == "running")

    # ---- 4. Find eligible tasks to spawn -----------------------------------
    # Priority: in-progress without a worker (crash recovery) first,
    # then not-started with all deps met.
    resuming: list[Task] = []
    ready: list[Task] = []

    for task in world.tasks.values():
        if task.status == TaskStatus.IN_PROGRESS and not _task_has_worker(task.id, world):
            resuming.append(task)
        elif task.status == TaskStatus.NOT_STARTED and _deps_met(task, world.tasks):
            ready.append(task)

    # Stable sort by task id for determinism
    resuming.sort(key=lambda t: t.id)
    ready.sort(key=lambda t: t.id)

    eligible = resuming + ready
    slots = max_workers - active_count
    to_spawn = eligible[:slots] if slots > 0 else []

    for task in to_spawn:
        actions.append(SpawnWorker(task_id=task.id, role="implementer"))

    # ---- 5. Check convergence: all complete + no workers → Halt ------------
    all_complete = all(t.status == TaskStatus.COMPLETE for t in world.tasks.values())
    no_workers = len(world.workers) == 0

    if world.tasks and all_complete and no_workers:
        actions.append(Halt(reason="all tasks complete"))

    return actions
