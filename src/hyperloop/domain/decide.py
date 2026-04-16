"""Decision function — given a World snapshot, return a list of Actions.

This is the orchestrator's brain: a pure function with no I/O dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hyperloop.domain.model import (
    AdvanceTask,
    Halt,
    ReapWorker,
    SpawnWorker,
    TaskStatus,
)

if TYPE_CHECKING:
    from hyperloop.domain.model import Action, Task, World


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


def decide(world: World, max_workers: int, max_task_rounds: int) -> list[Action]:
    """Decide what actions to take given the current world state.

    Returns an ordered list of actions: reaps first, then advances, then spawns,
    then halt if applicable.
    """
    actions: list[Action] = []

    # ---- 1. Reap finished workers (status == "done" or "failed") -----------
    for ws in world.workers.values():
        if ws.status in ("done", "failed"):
            actions.append(ReapWorker(task_id=ws.task_id))

    # ---- 2. Check for tasks that hit max_task_rounds → AdvanceTask + Halt ------
    for task in world.tasks.values():
        if task.status == TaskStatus.IN_PROGRESS and task.round >= max_task_rounds:
            actions.append(AdvanceTask(task_id=task.id, to_status=TaskStatus.FAILED, to_phase=None))
            reason = f"task {task.id} exceeded max_task_rounds ({max_task_rounds})"
            actions.append(Halt(reason=reason))
            return actions

    # ---- 3. Count active (running) workers ---------------------------------
    active_count = sum(1 for ws in world.workers.values() if ws.status == "running")

    # ---- 4. Find eligible tasks to spawn -----------------------------------
    # Priority order:
    #   1. needs-rebase tasks (rebase-resolver, from merge conflict handling)
    #   2. in-progress without a worker (crash recovery / pipeline resume)
    #   3. not-started with all deps met
    #
    # The role is a hint: "rebase-resolver" for needs-rebase tasks,
    # "implementer" as a default for others. The loop overrides the role
    # for in-progress tasks based on their pipeline position.
    needs_rebase: list[Task] = []
    resuming: list[Task] = []
    ready: list[Task] = []

    for task in world.tasks.values():
        if task.status == TaskStatus.NEEDS_REBASE and not _task_has_worker(task.id, world):
            needs_rebase.append(task)
        elif task.status == TaskStatus.IN_PROGRESS and not _task_has_worker(task.id, world):
            resuming.append(task)
        elif task.status == TaskStatus.NOT_STARTED and _deps_met(task, world.tasks):
            ready.append(task)

    # Stable sort by task id for determinism
    needs_rebase.sort(key=lambda t: t.id)
    resuming.sort(key=lambda t: t.id)
    ready.sort(key=lambda t: t.id)

    eligible = needs_rebase + resuming + ready
    slots = max_workers - active_count
    to_spawn = eligible[:slots] if slots > 0 else []

    for task in to_spawn:
        role = "rebase-resolver" if task.status == TaskStatus.NEEDS_REBASE else "implementer"
        actions.append(SpawnWorker(task_id=task.id, role=role))

    # ---- 5. Check convergence -----------------------------------------------
    no_workers = len(world.workers) == 0

    if world.tasks and no_workers:
        all_complete = all(t.status == TaskStatus.COMPLETE for t in world.tasks.values())
        if all_complete:
            actions.append(Halt(reason="all tasks complete"))
        elif not eligible:
            # No workers, nothing to spawn — check for deadlock.
            # If any task is failed and nothing is spawnable, we're stuck.
            failed = [t.id for t in world.tasks.values() if t.status == TaskStatus.FAILED]
            if failed:
                actions.append(
                    Halt(reason=f"deadlocked: failed tasks {failed} block remaining work")
                )

    return actions
