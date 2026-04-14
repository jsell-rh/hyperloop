"""Orchestrator loop — wires decide, pipeline, state store, and runtime.

Runs the serial section from the spec: reap finished workers, process results
through the pipeline, decide what to spawn, spawn workers, update state, and
check convergence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from k_orchestrate.domain.model import (
    LoopStep,
    Phase,
    PipelinePosition,
    PipelineStep,
    TaskStatus,
    Verdict,
    WorkerHandle,
)
from k_orchestrate.domain.pipeline import (
    PipelineComplete,
    PipelineFailed,
    SpawnRole,
    next_action,
)

if TYPE_CHECKING:
    from k_orchestrate.domain.model import WorkerResult, Workflow
    from k_orchestrate.ports.runtime import Runtime
    from k_orchestrate.ports.state import StateStore


class Orchestrator:
    """Main orchestrator loop — one serial section per cycle.

    The orchestrator tracks active workers and their pipeline positions.
    Each cycle: reap -> advance pipeline -> spawn -> update state -> check convergence.
    """

    def __init__(
        self,
        state: StateStore,
        runtime: Runtime,
        workflow: Workflow,
        max_workers: int = 6,
        max_rounds: int = 50,
    ) -> None:
        self._state = state
        self._runtime = runtime
        self._workflow = workflow
        self._max_workers = max_workers
        self._max_rounds = max_rounds

        # Active worker tracking: task_id -> (handle, pipeline_position)
        self._workers: dict[str, tuple[WorkerHandle, PipelinePosition]] = {}

    def run_loop(self, max_cycles: int = 1000) -> str:
        """Run the orchestrator loop until halt or max_cycles. Returns halt reason."""
        for _ in range(max_cycles):
            reason = self.run_cycle()
            if reason is not None:
                return reason
        return "max_cycles exhausted"

    def run_cycle(self) -> str | None:
        """Run one serial section cycle.

        Returns a halt reason string if the loop should stop, or None to continue.
        """
        pipeline = self._workflow.pipeline

        # ---- 1. Reap finished workers ----------------------------------------
        reaped: dict[str, WorkerResult] = {}
        finished_ids: list[str] = []

        for task_id, (handle, _pos) in self._workers.items():
            status = self._runtime.poll(handle)
            if status in ("done", "failed"):
                finished_ids.append(task_id)

        for task_id in finished_ids:
            handle, _pos = self._workers[task_id]
            result = self._runtime.reap(handle)
            reaped[task_id] = result

        # ---- 2. Process reaped results through pipeline ----------------------
        to_spawn: list[tuple[str, str, PipelinePosition]] = []  # (task_id, role, position)
        halt_reason: str | None = None

        for task_id, result in reaped.items():
            _handle, position = self._workers.pop(task_id)
            task = self._state.get_task(task_id)

            action, new_pos = next_action(pipeline, position, result)

            if isinstance(action, PipelineComplete):
                # Task completed the pipeline successfully
                self._state.transition_task(task_id, TaskStatus.COMPLETE, phase=None)
                self._state.clear_findings(task_id)

            elif isinstance(action, PipelineFailed):
                # Pipeline failed with no enclosing loop
                self._state.transition_task(task_id, TaskStatus.FAILED, phase=None)
                self._state.store_findings(task_id, result.detail)
                halt_reason = f"task {task_id} pipeline failed: {action.reason}"

            elif isinstance(action, SpawnRole):
                if result.verdict in (Verdict.FAIL, Verdict.ERROR, Verdict.TIMEOUT):
                    # Failure: increment round, store findings
                    new_round = task.round + 1
                    if new_round >= self._max_rounds:
                        self._state.transition_task(
                            task_id,
                            TaskStatus.FAILED,
                            phase=None,
                            round=new_round,
                        )
                        halt_reason = f"task {task_id} exceeded max_rounds ({self._max_rounds})"
                        continue
                    self._state.store_findings(task_id, result.detail)
                    self._state.transition_task(
                        task_id,
                        TaskStatus.IN_PROGRESS,
                        phase=Phase(action.role),
                        round=new_round,
                    )
                else:
                    # Pass: advancing to next step in pipeline
                    self._state.transition_task(
                        task_id,
                        TaskStatus.IN_PROGRESS,
                        phase=Phase(action.role),
                    )
                # Queue for spawning
                to_spawn.append((task_id, action.role, new_pos))

            else:
                # WaitForGate, PerformAction — record phase, don't spawn
                phase_name = _phase_for_action(action)
                self._state.transition_task(
                    task_id,
                    TaskStatus.IN_PROGRESS,
                    phase=Phase(phase_name) if phase_name else None,
                )

        # Check for halt from reaped processing
        if halt_reason is not None:
            self._state.commit("orchestrator: halt")
            return halt_reason

        # ---- 3. Decide what new tasks to spawn (not from reap) ---------------
        # Count currently active workers (still running + about to be spawned from reap)
        already_spawning = {tid for tid, _role, _pos in to_spawn}
        active_count = len(self._workers) + len(to_spawn)
        slots = self._max_workers - active_count

        if slots > 0:
            eligible = [tid for tid in self._find_eligible_tasks() if tid not in already_spawning]
            for task_id in eligible[:slots]:
                # Find the first leaf position in the pipeline
                pos = _find_initial_position(pipeline)
                action, pos = next_action(pipeline, pos, result=None)

                if isinstance(action, SpawnRole):
                    self._state.transition_task(
                        task_id,
                        TaskStatus.IN_PROGRESS,
                        phase=Phase(action.role),
                    )
                    to_spawn.append((task_id, action.role, pos))

        # ---- 4. Spawn workers ------------------------------------------------
        for task_id, role, position in to_spawn:
            task = self._state.get_task(task_id)
            branch = task.branch or f"worker/{task_id}"
            handle = self._runtime.spawn(task_id, role, prompt="", branch=branch)
            self._workers[task_id] = (handle, position)

        # ---- 5. Commit state -------------------------------------------------
        if reaped or to_spawn:
            self._state.commit("orchestrator: cycle update")

        # ---- 6. Check convergence --------------------------------------------
        all_tasks = self._state.get_world().tasks
        if not all_tasks:
            return None

        all_complete = all(t.status == TaskStatus.COMPLETE for t in all_tasks.values())
        no_workers = len(self._workers) == 0

        if all_complete and no_workers:
            return "all tasks complete"

        return None

    def _find_eligible_tasks(self) -> list[str]:
        """Find tasks eligible for spawning, in priority order.

        Priority: in-progress without a worker (crash recovery) first,
        then not-started with all deps met.
        """
        world = self._state.get_world()
        active_task_ids = set(self._workers.keys())

        resuming: list[str] = []
        ready: list[str] = []

        for task in world.tasks.values():
            if task.id in active_task_ids:
                continue
            if task.status == TaskStatus.IN_PROGRESS:
                resuming.append(task.id)
            elif task.status == TaskStatus.NOT_STARTED and self._deps_met(task.id, world.tasks):
                ready.append(task.id)

        resuming.sort()
        ready.sort()
        return resuming + ready

    def _deps_met(self, task_id: str, tasks: dict[str, object]) -> bool:
        """Check if all dependencies of a task are complete."""
        task = self._state.get_task(task_id)
        for dep_id in task.deps:
            dep_task = self._state.get_world().tasks.get(dep_id)
            if dep_task is None or dep_task.status != TaskStatus.COMPLETE:
                return False
        return True


def _phase_for_action(action: object) -> str | None:
    """Extract a phase name from a pipeline action."""
    from k_orchestrate.domain.pipeline import PerformAction, WaitForGate

    if isinstance(action, WaitForGate):
        return action.gate
    if isinstance(action, PerformAction):
        return action.action
    return None


def _find_initial_position(
    steps: tuple[PipelineStep, ...],
) -> PipelinePosition:
    """Find the position of the first leaf step, descending into LoopSteps.

    For a pipeline like (LoopStep((impl, verifier)),), returns pos(0, 0)
    pointing to the implementer inside the loop.
    """
    path: list[int] = [0]
    step: PipelineStep = steps[0]
    while isinstance(step, LoopStep):
        path.append(0)
        step = step.steps[0]
    return PipelinePosition(path=tuple(path))
