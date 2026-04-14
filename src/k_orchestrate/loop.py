"""Orchestrator loop — wires decide, pipeline, state store, and runtime.

Runs the serial section from the spec: reap finished workers, check for halt,
run stubs for process-improver/intake/gates/merge, decide what to spawn,
update state, spawn workers, and check convergence.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from k_orchestrate.domain.decide import decide
from k_orchestrate.domain.model import (
    Halt,
    LoopStep,
    Phase,
    PipelinePosition,
    ReapWorker,
    RoleStep,
    SpawnWorker,
    TaskStatus,
    Verdict,
    WorkerHandle,
    WorkerState,
    World,
)
from k_orchestrate.domain.pipeline import (
    PipelineComplete,
    PipelineExecutor,
    PipelineFailed,
    SpawnRole,
)

if TYPE_CHECKING:
    from k_orchestrate.domain.model import PipelineStep, Task, WorkerResult, Workflow
    from k_orchestrate.ports.runtime import Runtime
    from k_orchestrate.ports.state import StateStore

logger = logging.getLogger(__name__)


class Orchestrator:
    """Main orchestrator loop — one serial section per cycle.

    The orchestrator tracks active workers and their pipeline positions.
    Each cycle follows the spec's serial section order:
      1. Reap finished workers
      2. Halt if any task failed
      3. Process-improver (stub)
      4. Intake (stub)
      5. Poll gates (stub)
      6. Merge ready PRs (stub)
      7. Decide what to spawn (via decide())
      8. Update state (transition tasks, commit)
      9. Spawn workers
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

    def recover(self) -> None:
        """Recover from a crash by reconciling persisted state with runtime.

        Reads all tasks from the state store. For IN_PROGRESS tasks with no
        active worker: checks for orphaned workers via the runtime and cancels
        them, then adds the task to internal tracking for re-spawn.
        """
        world = self._state.get_world()

        for task in world.tasks.values():
            if task.status != TaskStatus.IN_PROGRESS:
                continue
            if task.id in self._workers:
                continue

            branch = task.branch or f"worker/{task.id}"

            # Check for orphaned workers left from a previous session
            orphan = self._runtime.find_orphan(task.id, branch)
            if orphan is not None:
                self._runtime.cancel(orphan)

            # Create a placeholder handle so decide() sees this task as
            # needing a worker (it will be re-spawned in the next cycle)
            # We don't add to _workers here — instead leave it workerless
            # so decide() will emit a SpawnWorker for it next cycle.
            logger.info(
                "recover: task %s is IN_PROGRESS at phase %s, will re-spawn",
                task.id,
                task.phase,
            )

    def run_cycle(self) -> str | None:
        """Run one serial section cycle.

        Returns a halt reason string if the loop should stop, or None to continue.
        """
        executor = PipelineExecutor(self._workflow.pipeline)

        # Cache world snapshot once per cycle — augmented with worker state
        world = self._build_world()

        # ---- 1. Reap finished workers ----------------------------------------
        reaped_results: dict[str, WorkerResult] = {}
        had_failures_this_cycle = False

        actions = decide(world, self._max_workers, self._max_rounds)

        # Process ReapWorker actions from decide()
        for action in actions:
            if isinstance(action, ReapWorker):
                task_id = action.task_id
                if task_id in self._workers:
                    handle, _pos = self._workers[task_id]
                    result = self._runtime.reap(handle)
                    reaped_results[task_id] = result

        # ---- 2. Process reaped results through pipeline ----------------------
        to_spawn: list[tuple[str, str, PipelinePosition]] = []
        halt_reason: str | None = None

        for task_id, result in reaped_results.items():
            _handle, position = self._workers.pop(task_id)
            task = self._state.get_task(task_id)

            pipe_action, new_pos = executor.next_action(position, result)

            if isinstance(pipe_action, PipelineComplete):
                self._state.transition_task(task_id, TaskStatus.COMPLETE, phase=None)
                self._state.clear_findings(task_id)

            elif isinstance(pipe_action, PipelineFailed):
                self._state.transition_task(task_id, TaskStatus.FAILED, phase=None)
                self._state.store_findings(task_id, result.detail)
                halt_reason = f"task {task_id} pipeline failed: {pipe_action.reason}"
                had_failures_this_cycle = True

            elif isinstance(pipe_action, SpawnRole):
                if result.verdict in (Verdict.FAIL, Verdict.ERROR, Verdict.TIMEOUT):
                    had_failures_this_cycle = True
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
                        phase=Phase(pipe_action.role),
                        round=new_round,
                    )
                else:
                    self._state.transition_task(
                        task_id,
                        TaskStatus.IN_PROGRESS,
                        phase=Phase(pipe_action.role),
                    )
                to_spawn.append((task_id, pipe_action.role, new_pos))

            else:
                # WaitForGate, PerformAction — record phase, don't spawn
                phase_name = _phase_for_action(pipe_action)
                self._state.transition_task(
                    task_id,
                    TaskStatus.IN_PROGRESS,
                    phase=Phase(phase_name) if phase_name else None,
                )

        # ---- 2b. Halt if any task failed -------------------------------------
        if halt_reason is not None:
            self._state.commit("orchestrator: halt")
            return halt_reason

        # ---- 3. Process-improver (stub) --------------------------------------
        if had_failures_this_cycle:
            # TODO: run process-improver agent once on trunk, reading all
            # findings from this cycle. For now, log and skip.
            logger.info("process-improver: stub — would run on trunk with this cycle's findings")

        # ---- 4. Intake (stub) ------------------------------------------------
        # TODO: run PM intake if configured and new specs exist.
        # For now, log and skip.
        logger.debug("intake: stub — would run if configured and new specs exist")

        # ---- 5. Poll gates (stub) --------------------------------------------
        # TODO: for tasks at a gate step, check PR labels for lgtm.
        # When found, clear gate and advance task.
        logger.debug("gates: stub — would poll PR labels for lgtm")

        # ---- 6. Merge ready PRs (stub) ---------------------------------------
        # TODO: squash-merge ready PRs one at a time in dependency order.
        # Will be implemented with GitStateStore.
        logger.debug("merge: stub — would merge ready PRs")

        # ---- 7. Decide what to spawn (via decide()) -------------------------
        # Rebuild world after reaping (tasks may have changed status)
        world_after_reap = self._build_world()
        spawn_actions = decide(world_after_reap, self._max_workers, self._max_rounds)

        # Check for Halt from decide() (convergence or max_rounds)
        for action in spawn_actions:
            if isinstance(action, Halt):
                self._state.commit("orchestrator: halt")
                return action.reason

        # Process SpawnWorker actions
        already_spawning = {tid for tid, _role, _pos in to_spawn}
        for action in spawn_actions:
            if isinstance(action, SpawnWorker) and action.task_id not in already_spawning:
                task = self._state.get_task(action.task_id)

                if action.role == "rebase-resolver":
                    # NEEDS_REBASE tasks get rebase-resolver role directly
                    pos = executor.initial_position()
                    self._state.transition_task(
                        action.task_id,
                        TaskStatus.IN_PROGRESS,
                        phase=Phase("rebase-resolver"),
                    )
                    to_spawn.append((action.task_id, "rebase-resolver", pos))
                elif task.status == TaskStatus.IN_PROGRESS and task.phase is not None:
                    # Resuming an in-progress task — use its current phase
                    pos = self._position_from_phase(executor, task)
                    to_spawn.append((action.task_id, str(task.phase), pos))
                else:
                    # New task — start at the beginning of the pipeline
                    pos = executor.initial_position()
                    pipe_action, pos = executor.next_action(pos, result=None)
                    if isinstance(pipe_action, SpawnRole):
                        self._state.transition_task(
                            action.task_id,
                            TaskStatus.IN_PROGRESS,
                            phase=Phase(pipe_action.role),
                        )
                        to_spawn.append((action.task_id, pipe_action.role, pos))

        # ---- 8. Commit state -------------------------------------------------
        if reaped_results or to_spawn:
            self._state.commit("orchestrator: cycle update")

        # ---- 9. Spawn workers ------------------------------------------------
        for task_id, role, position in to_spawn:
            task = self._state.get_task(task_id)
            branch = task.branch or f"worker/{task_id}"
            handle = self._runtime.spawn(task_id, role, prompt="", branch=branch)
            self._workers[task_id] = (handle, position)

        # ---- Check convergence -----------------------------------------------
        all_tasks = self._state.get_world().tasks
        if not all_tasks:
            return None

        all_complete = all(t.status == TaskStatus.COMPLETE for t in all_tasks.values())
        no_workers = len(self._workers) == 0

        if all_complete and no_workers:
            return "all tasks complete"

        return None

    def _build_world(self) -> World:
        """Build a World snapshot including current worker state from runtime.

        The state store's get_world() returns tasks but no workers. This method
        augments it with the orchestrator's tracked workers and their poll status.
        """
        base_world = self._state.get_world()
        workers: dict[str, WorkerState] = {}
        for task_id, (handle, _pos) in self._workers.items():
            poll_status = self._runtime.poll(handle)
            workers[task_id] = WorkerState(
                task_id=task_id,
                role=handle.role,
                status=poll_status,
            )
        return World(
            tasks=base_world.tasks,
            workers=workers,
            epoch=base_world.epoch,
        )

    def _position_from_phase(self, executor: PipelineExecutor, task: Task) -> PipelinePosition:
        """Determine pipeline position from a task's current phase.

        Walks the pipeline to find the step matching the task's phase.
        Falls back to initial position if no match is found.
        """
        if task.phase is not None:
            pos = self._find_position_for_role(executor, str(task.phase))
            if pos is not None:
                return pos
        return executor.initial_position()

    @staticmethod
    def _find_position_for_role(executor: PipelineExecutor, role: str) -> PipelinePosition | None:
        """Walk the pipeline to find a position matching the given role name.

        Searches the pipeline depth-first for a RoleStep with the matching role.
        """

        def _search(
            steps: tuple[PipelineStep, ...], prefix: tuple[int, ...]
        ) -> PipelinePosition | None:
            for i, step in enumerate(steps):
                path = (*prefix, i)
                if isinstance(step, RoleStep) and step.role == role:
                    return PipelinePosition(path=path)
                if isinstance(step, LoopStep):
                    found = _search(step.steps, path)
                    if found is not None:
                        return found
            return None

        return _search(executor._pipeline, ())


def _phase_for_action(action: object) -> str | None:
    """Extract a phase name from a pipeline action."""
    from k_orchestrate.domain.pipeline import PerformAction, WaitForGate

    if isinstance(action, WaitForGate):
        return action.gate
    if isinstance(action, PerformAction):
        return action.action
    return None
