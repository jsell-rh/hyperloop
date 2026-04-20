"""Orchestrator loop -- wires decide, pipeline, state store, and runtime.

Runs a 4-phase cycle: COLLECT, INTAKE, ADVANCE, SPAWN.
Uses pluggable ports (GatePort, ActionPort, CycleHook, NotificationPort)
for all external interactions.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from hyperloop.adapters.notification.null import NullNotification
from hyperloop.adapters.probe import NullProbe
from hyperloop.domain.decide import decide
from hyperloop.domain.deps import detect_cycles
from hyperloop.domain.model import (
    ActionStep,
    AgentStep,
    GateStep,
    Halt,
    IntakeContext,
    LoopStep,
    Phase,
    PipelinePosition,
    ReapWorker,
    SpawnWorker,
    TaskContext,
    TaskStatus,
    Verdict,
    WorkerHandle,
    WorkerState,
    World,
)
from hyperloop.domain.pipeline import (
    PerformAction,
    PipelineComplete,
    PipelineExecutor,
    PipelineFailed,
    SpawnAgent,
    WaitForGate,
)
from hyperloop.ports.action import ActionOutcome

if TYPE_CHECKING:
    from hyperloop.compose import PromptComposer
    from hyperloop.domain.model import PipelineStep, Process, Task, WorkerResult
    from hyperloop.ports.action import ActionPort
    from hyperloop.ports.gate import GatePort
    from hyperloop.ports.hook import CycleHook
    from hyperloop.ports.notification import NotificationPort
    from hyperloop.ports.probe import OrchestratorProbe
    from hyperloop.ports.runtime import Runtime
    from hyperloop.ports.state import StateStore

logger: structlog.stdlib.BoundLogger = structlog.get_logger()

BRANCH_PREFIX = "hyperloop"


class Orchestrator:
    """Main orchestrator loop -- 4-phase cycle with pluggable ports.

    Each cycle follows four phases:
      1. COLLECT -- reap finished workers, run hooks
      2. INTAKE -- detect spec gaps, create work
      3. ADVANCE -- advance tasks through pipeline (gates, actions, results)
      4. SPAWN -- decide, spawn workers
    """

    def __init__(
        self,
        state: StateStore,
        runtime: Runtime,
        process: Process,
        max_workers: int = 6,
        max_task_rounds: int = 50,
        max_action_attempts: int = 3,
        gate: GatePort | None = None,
        action: ActionPort | None = None,
        hooks: tuple[CycleHook, ...] = (),
        notification: NotificationPort | None = None,
        composer: PromptComposer | None = None,
        poll_interval: float = 30.0,
        probe: OrchestratorProbe | None = None,
    ) -> None:
        self._state = state
        self._runtime = runtime
        self._process = process
        self._max_workers = max_workers
        self._max_task_rounds = max_task_rounds
        self._max_action_attempts = max_action_attempts
        self._gate = gate
        self._action = action
        self._hooks = hooks
        self._notification: NotificationPort = notification or NullNotification()
        self._composer = composer
        self._poll_interval = poll_interval
        self._probe = probe or NullProbe()

        # Active worker tracking: task_id -> (handle, pipeline_position, spawn_time)
        self._workers: dict[str, tuple[WorkerHandle, PipelinePosition, float]] = {}
        # Action attempt count per task
        self._action_attempts: dict[str, int] = {}
        # Current cycle number -- set at the start of each run_cycle
        self._current_cycle: int = 0
        # Spawn backoff: global consecutive failures + per-task retry counts
        self._spawn_failures: int = 0
        self._spawn_skip_until: int = 0
        self._spawn_task_failures: dict[str, int] = {}
        # Notification deduplication: task_ids that have been notified for gate_blocked
        self._notified_gates: set[str] = set()
        # Halt reason set during collect phase
        self._halt_reason: str | None = None

    def validate_templates(self) -> None:
        """Validate that every role in the pipeline has a resolved template.

        Call at startup before ``run_loop`` to catch configuration errors
        early instead of crashing mid-run when a task reaches an unknown role.

        Raises:
            ValueError: If any pipeline role has no resolved template.
        """
        if self._composer is None:
            return

        roles = _collect_roles(self._process.pipeline)
        missing = [r for r in roles if r not in self._composer._templates]
        if missing:
            msg = (
                f"Pipeline references roles with no agent template: {sorted(missing)}. "
                "Check that base/ has definitions for these roles and "
                "kustomize build resolves them."
            )
            raise ValueError(msg)

    def run_loop(self, max_cycles: int = 200) -> str:
        """Run the orchestrator loop until halt or max_cycles. Returns halt reason."""
        self.validate_templates()
        world = self._state.get_world()
        self._probe.orchestrator_started(
            task_count=len(world.tasks),
            max_workers=self._max_workers,
            max_task_rounds=self._max_task_rounds,
        )
        for cycle_num in range(max_cycles):
            reason = self.run_cycle(cycle_num=cycle_num + 1)
            if reason is not None:
                self._emit_halted(reason, cycle_num + 1)
                return reason
            if self._poll_interval > 0:
                time.sleep(self._poll_interval)
        reason = "max_cycles exhausted"
        self._emit_halted(reason, max_cycles)
        return reason

    def _emit_halted(self, reason: str, total_cycles: int) -> None:
        """Emit orchestrator_halted probe event."""
        world = self._state.get_world()
        self._probe.orchestrator_halted(
            reason=reason,
            total_cycles=total_cycles,
            completed_tasks=sum(1 for t in world.tasks.values() if t.status == TaskStatus.COMPLETE),
            failed_tasks=sum(1 for t in world.tasks.values() if t.status == TaskStatus.FAILED),
        )

    def recover(self) -> None:
        """Recover from a crash by reconciling persisted state with runtime.

        Reads all tasks from the state store. For IN_PROGRESS tasks with no
        active worker: checks for orphaned workers via the runtime and cancels
        them, then adds the task to internal tracking for re-spawn.
        """
        world = self._state.get_world()

        cycles = detect_cycles(world.tasks)
        if cycles:
            formatted = "; ".join(" -> ".join(c) for c in cycles)
            raise RuntimeError(f"Dependency cycle(s) detected in task graph: {formatted}")

        self._probe.recovery_started(
            in_progress_tasks=sum(
                1 for t in world.tasks.values() if t.status == TaskStatus.IN_PROGRESS
            ),
        )

        for task in world.tasks.values():
            if task.status != TaskStatus.IN_PROGRESS:
                continue
            if task.id in self._workers:
                continue

            branch = task.branch or f"{BRANCH_PREFIX}/{task.id}"

            # Check for orphaned workers left from a previous session
            orphan = self._runtime.find_orphan(task.id, branch)
            if orphan is not None:
                self._runtime.cancel(orphan)
                self._probe.orphan_found(task_id=task.id, branch=branch)

            # We don't add to _workers here -- instead leave it workerless
            # so decide() will emit a SpawnWorker for it next cycle.
            logger.info(
                "recover: task %s is IN_PROGRESS at phase %s, will re-spawn",
                task.id,
                task.phase,
            )

    def run_cycle(self, cycle_num: int = 0) -> str | None:
        """Run one 4-phase cycle.

        Returns a halt reason string if the loop should stop, or None to continue.
        """
        self._current_cycle = cycle_num
        cycle_start = time.monotonic()
        executor = PipelineExecutor(self._process.pipeline)

        # Cache world snapshot once per cycle -- augmented with worker state
        world = self._build_world()

        # ---- 0. Early exit on zero tasks ----------------------------------------
        if not world.tasks and not self._workers:
            # Try intake first -- it may create tasks from new specs
            self._run_intake()
            world = self._build_world()
            if not world.tasks and not self._workers:
                reason = "no tasks found -- nothing to do"
                return reason

        self._probe.cycle_started(
            cycle=cycle_num,
            active_workers=len(self._workers),
            not_started=sum(1 for t in world.tasks.values() if t.status == TaskStatus.NOT_STARTED),
            in_progress=sum(1 for t in world.tasks.values() if t.status == TaskStatus.IN_PROGRESS),
            complete=sum(1 for t in world.tasks.values() if t.status == TaskStatus.COMPLETE),
            failed=sum(1 for t in world.tasks.values() if t.status == TaskStatus.FAILED),
        )

        # ==== PHASE 1: COLLECT ====
        reaped_results = self._collect(cycle_num, executor)

        # Run hooks after reap
        if reaped_results:
            for hook in self._hooks:
                hook.after_reap(results=reaped_results, cycle=cycle_num)

        # Check for halt from COLLECT (pipeline failures)
        halt_reason = self._check_halt_from_results(cycle_num)
        if halt_reason is not None:
            self._state.persist("orchestrator: halt")
            return halt_reason

        # ==== PHASE 2: INTAKE ====
        self._run_intake()

        # ==== PHASE 3: ADVANCE ====
        halt_reason = self._advance(cycle_num, executor)
        if halt_reason is not None:
            self._state.persist("orchestrator: halt")
            return halt_reason

        # ==== PHASE 4: SPAWN ====
        to_spawn = self._spawn(cycle_num, executor)

        # ---- Persist state -------
        self._state.persist("orchestrator: cycle update")

        # ---- Execute spawns ------
        self._execute_spawns(to_spawn, cycle_num)

        # ---- Check convergence ----
        self._emit_cycle_completed(cycle_num, cycle_start, to_spawn, reaped_results)
        return self._check_convergence()

    # -----------------------------------------------------------------------
    # PHASE 1: COLLECT -- reap finished workers
    # -----------------------------------------------------------------------

    def _collect(
        self,
        cycle_num: int,
        executor: PipelineExecutor,
    ) -> dict[str, WorkerResult]:
        """Reap finished workers. Returns dict of task_id -> WorkerResult."""
        world = self._build_world()
        actions = decide(world, self._max_workers, self._max_task_rounds)

        reaped_results: dict[str, WorkerResult] = {}
        for act in actions:
            if isinstance(act, ReapWorker):
                task_id = act.task_id
                if task_id in self._workers:
                    handle, _pos, _spawn_time = self._workers[task_id]
                    result = self._runtime.reap(handle)
                    reaped_results[task_id] = result

        # Process reaped results through pipeline
        for task_id, result in reaped_results.items():
            _handle, position, spawn_time = self._workers.pop(task_id)
            task = self._state.get_task(task_id)

            self._probe.worker_reaped(
                task_id=task_id,
                role=_handle.role,
                verdict=result.verdict.value,
                round=task.round,
                cycle=cycle_num,
                spec_ref=task.spec_ref,
                detail=result.detail,
                duration_s=time.monotonic() - spawn_time,
            )

            pipe_action, _new_pos = executor.next_action(position, result)

            if isinstance(pipe_action, PipelineComplete):
                self._state.transition_task(task_id, TaskStatus.COMPLETE, phase=None)
                self._probe.task_completed(
                    task_id=task_id,
                    spec_ref=task.spec_ref,
                    total_rounds=task.round,
                    total_cycles=cycle_num,
                    cycle=cycle_num,
                )

            elif isinstance(pipe_action, PipelineFailed):
                self._state.transition_task(task_id, TaskStatus.FAILED, phase=None)
                self._state.store_review(
                    task_id,
                    round=task.round,
                    role=_handle.role,
                    verdict=result.verdict.value,
                    detail=result.detail,
                )
                self._halt_reason = f"task {task_id} pipeline failed: {pipe_action.reason}"
                self._probe.task_failed(
                    task_id=task_id,
                    spec_ref=task.spec_ref,
                    reason=pipe_action.reason,
                    round=task.round,
                    cycle=cycle_num,
                )

            elif isinstance(pipe_action, SpawnAgent):
                if result.verdict == Verdict.FAIL:
                    new_round = task.round + 1
                    if new_round >= self._max_task_rounds:
                        self._state.transition_task(
                            task_id,
                            TaskStatus.FAILED,
                            phase=None,
                            round=new_round,
                        )
                        self._halt_reason = (
                            f"task {task_id} exceeded max_task_rounds ({self._max_task_rounds})"
                        )
                        self._probe.task_failed(
                            task_id=task_id,
                            spec_ref=task.spec_ref,
                            reason=f"exceeded max_task_rounds ({self._max_task_rounds})",
                            round=new_round,
                            cycle=cycle_num,
                        )
                        continue
                    self._state.store_review(
                        task_id,
                        round=task.round,
                        role=_handle.role,
                        verdict=result.verdict.value,
                        detail=result.detail,
                    )
                    self._state.transition_task(
                        task_id,
                        TaskStatus.IN_PROGRESS,
                        phase=Phase(pipe_action.agent),
                        round=new_round,
                    )
                    self._probe.task_looped_back(
                        task_id=task_id,
                        spec_ref=task.spec_ref,
                        round=new_round,
                        cycle=cycle_num,
                        findings_preview=result.detail[:200],
                    )
                else:
                    # Advancing forward on PASS -- create draft PR if needed
                    if task.pr is None and hasattr(self._gate, "_pr"):
                        branch = task.branch or f"{BRANCH_PREFIX}/{task_id}"
                        pr_url = self._gate._pr.create_draft(  # type: ignore[union-attr]
                            task_id,
                            branch,
                            task.title,
                            task.spec_ref,
                        )
                        if pr_url:
                            self._state.set_task_pr(task_id, pr_url)

                    self._state.transition_task(
                        task_id,
                        TaskStatus.IN_PROGRESS,
                        phase=Phase(pipe_action.agent),
                    )
                    self._probe.task_advanced(
                        task_id=task_id,
                        spec_ref=task.spec_ref,
                        from_phase=str(task.phase) if task.phase else None,
                        to_phase=pipe_action.agent,
                        from_status=task.status.value,
                        to_status=TaskStatus.IN_PROGRESS.value,
                        round=task.round,
                        cycle=cycle_num,
                    )

            else:
                # WaitForGate, PerformAction -- record phase, don't spawn
                phase_name = _phase_for_action(pipe_action)
                self._state.transition_task(
                    task_id,
                    TaskStatus.IN_PROGRESS,
                    phase=Phase(phase_name) if phase_name else None,
                )
                self._probe.task_advanced(
                    task_id=task_id,
                    spec_ref=task.spec_ref,
                    from_phase=str(task.phase) if task.phase else None,
                    to_phase=phase_name,
                    from_status=task.status.value,
                    to_status=TaskStatus.IN_PROGRESS.value,
                    round=task.round,
                    cycle=cycle_num,
                )

        return reaped_results

    def _check_halt_from_results(
        self,
        cycle_num: int,
    ) -> str | None:
        """Check if any task was marked FAILED during collect -> halt."""
        # Track halt reasons set during _collect
        if self._halt_reason is not None:
            reason = self._halt_reason
            self._halt_reason = None
            return reason
        return None

    # -----------------------------------------------------------------------
    # PHASE 3: ADVANCE -- advance tasks through gates and actions
    # -----------------------------------------------------------------------

    def _advance(
        self,
        cycle_num: int,
        executor: PipelineExecutor,
    ) -> str | None:
        """Advance tasks through gates and actions. Returns halt reason or None."""
        all_tasks = self._state.get_world().tasks

        for task in all_tasks.values():
            if task.status != TaskStatus.IN_PROGRESS:
                continue
            if task.phase is None:
                continue
            if task.id in self._workers:
                continue  # Worker running, don't advance

            pos = self._find_position_for_step(executor, str(task.phase))
            if pos is None:
                continue

            step = PipelineExecutor.resolve_step(executor.pipeline, pos.path)

            # -- Gate step --
            if isinstance(step, GateStep):
                halt = self._advance_gate(task, step, pos, executor, cycle_num)
                if halt is not None:
                    return halt

            # -- Action step --
            elif isinstance(step, ActionStep):
                halt = self._advance_action(task, step, pos, executor, cycle_num)
                if halt is not None:
                    return halt

        return None

    def _advance_gate(
        self,
        task: Task,
        step: GateStep,
        pos: PipelinePosition,
        executor: PipelineExecutor,
        cycle_num: int,
    ) -> str | None:
        """Handle a task at a gate step. Returns halt reason or None."""
        if self._gate is None:
            logger.debug("gates: no gate adapter -- skipping gate polling")
            return None

        # Ensure the task has a PR -- create one if missing
        if task.pr is None and hasattr(self._gate, "_pr"):
            branch = task.branch or f"{BRANCH_PREFIX}/{task.id}"
            pr_url = self._gate._pr.create_draft(  # type: ignore[union-attr]
                task.id, branch, task.title, task.spec_ref
            )
            if pr_url:
                self._state.set_task_pr(task.id, pr_url)
                task = self._state.get_task(task.id)
            else:
                return None  # Can't poll gate without a PR

        # Handle CLOSED PRs: recreate before checking gate
        if task.pr is not None and hasattr(self._gate, "_pr"):
            pr_state = self._gate._pr.get_pr_state(task.pr)  # type: ignore[union-attr]
            if pr_state is not None and pr_state.state == "CLOSED":
                branch = task.branch or f"{BRANCH_PREFIX}/{task.id}"
                new_url = self._gate._pr.create_draft(  # type: ignore[union-attr]
                    task.id, branch, task.title, task.spec_ref
                )
                if new_url:
                    self._state.set_task_pr(task.id, new_url)
                    task = self._state.get_task(task.id)
                else:
                    return None

        # Notification deduplication: notify once per gate entry
        if task.id not in self._notified_gates:
            self._notification.gate_blocked(task=task, gate_name=step.gate)
            self._notified_gates.add(task.id)

        cleared = self._gate.check(task, step.gate)
        self._probe.gate_checked(
            task_id=task.id,
            gate=step.gate,
            cleared=cleared,
            cycle=cycle_num,
        )

        if not cleared:
            return None

        # Gate cleared -- remove from notified set and advance
        self._notified_gates.discard(task.id)

        # Check if the gate check returned True because PR was merged
        # (LabelGate returns True for MERGED PRs)
        if task.pr is not None and hasattr(self._gate, "_pr"):
            pr_state_check = self._gate._pr.get_pr_state(task.pr)  # type: ignore[union-attr]
            if pr_state_check is not None and pr_state_check.state == "MERGED":
                self._state.transition_task(task.id, TaskStatus.COMPLETE, phase=None)
                self._probe.merge_attempted(
                    task_id=task.id,
                    branch=task.branch or f"{BRANCH_PREFIX}/{task.id}",
                    spec_ref=task.spec_ref,
                    outcome="merged_externally",
                    attempt=0,
                    cycle=cycle_num,
                )
                return None

        advanced = PipelineExecutor.advance_from(executor.pipeline, pos.path)
        if advanced is not None:
            next_action, _new_pos = advanced
            phase_name = _phase_for_pipe_action(next_action)
            self._state.transition_task(
                task.id,
                TaskStatus.IN_PROGRESS,
                phase=Phase(phase_name) if phase_name else None,
            )
        else:
            self._state.transition_task(task.id, TaskStatus.COMPLETE, phase=None)

        return None

    def _advance_action(
        self,
        task: Task,
        step: ActionStep,
        pos: PipelinePosition,
        executor: PipelineExecutor,
        cycle_num: int,
    ) -> str | None:
        """Handle a task at an action step. Returns halt reason or None."""
        if self._action is None:
            logger.debug(
                "actions: no action adapter -- skipping action %s",
                step.action,
            )
            return None

        result = self._action.execute(task, step.action)

        if result.outcome == ActionOutcome.SUCCESS:
            # Update PR URL if the action recreated it
            if result.pr_url is not None:
                self._state.set_task_pr(task.id, result.pr_url)
            self._action_attempts.pop(task.id, None)
            self._probe.merge_attempted(
                task_id=task.id,
                branch=task.branch or f"{BRANCH_PREFIX}/{task.id}",
                spec_ref=task.spec_ref,
                outcome="merged",
                attempt=0,
                cycle=cycle_num,
            )

            # Advance past action or complete
            advanced = PipelineExecutor.advance_from(executor.pipeline, pos.path)
            if advanced is not None:
                next_act, _new_pos = advanced
                phase_name = _phase_for_pipe_action(next_act)
                self._state.transition_task(
                    task.id,
                    TaskStatus.IN_PROGRESS,
                    phase=Phase(phase_name) if phase_name else None,
                )
            else:
                self._state.transition_task(task.id, TaskStatus.COMPLETE, phase=None)

        elif result.outcome == ActionOutcome.RETRY:
            # Update PR URL if the action recreated it
            if result.pr_url is not None:
                self._state.set_task_pr(task.id, result.pr_url)
            # Stay at current step, try again next cycle

        elif result.outcome == ActionOutcome.ERROR:
            attempts = self._action_attempts.get(task.id, 0) + 1
            self._action_attempts[task.id] = attempts

            looping_back = attempts >= self._max_action_attempts
            self._probe.rebase_conflict(
                task_id=task.id,
                branch=task.branch or f"{BRANCH_PREFIX}/{task.id}",
                attempt=attempts,
                max_attempts=self._max_action_attempts,
                looping_back=looping_back,
                cycle=cycle_num,
            )

            if looping_back:
                self._action_attempts.pop(task.id, None)
                detail = f"Action error after {self._max_action_attempts} attempts: {result.detail}"
                self._state.store_review(
                    task.id,
                    round=task.round,
                    role="orchestrator",
                    verdict="fail",
                    detail=detail,
                )
                self._state.transition_task(
                    task.id,
                    TaskStatus.IN_PROGRESS,
                    phase=Phase("implementer"),
                    round=task.round + 1,
                )
            else:
                # Stay at merge-pr, retry next cycle
                self._state.transition_task(
                    task.id,
                    TaskStatus.IN_PROGRESS,
                    phase=Phase(step.action),
                )

        return None

    # -----------------------------------------------------------------------
    # PHASE 4: SPAWN -- decide and spawn workers
    # -----------------------------------------------------------------------

    def _spawn(
        self,
        cycle_num: int,
        executor: PipelineExecutor,
    ) -> list[tuple[str, str, PipelinePosition]]:
        """Decide what to spawn and return spawn list."""
        to_spawn: list[tuple[str, str, PipelinePosition]] = []

        # Rebuild world after reaping + gates + actions
        world_after = self._build_world()
        spawn_actions = decide(world_after, self._max_workers, self._max_task_rounds)

        # Check for Halt from decide()
        for act in spawn_actions:
            if isinstance(act, Halt):
                # We can't return halt from here; check convergence will catch it
                pass

        for act in spawn_actions:
            if not isinstance(act, SpawnWorker):
                continue

            task = self._state.get_task(act.task_id)

            if act.role == "rebase-resolver":
                pos = executor.initial_position()
                self._state.transition_task(
                    act.task_id,
                    TaskStatus.IN_PROGRESS,
                    phase=Phase("rebase-resolver"),
                )
                to_spawn.append((act.task_id, "rebase-resolver", pos))
            elif task.status == TaskStatus.IN_PROGRESS and task.phase is not None:
                # Only spawn for agent steps -- gates and actions are handled in ADVANCE
                phase_name = str(task.phase)
                pos = self._find_position_for_step(executor, phase_name)
                if pos is not None:
                    step = PipelineExecutor.resolve_step(executor.pipeline, pos.path)
                    if isinstance(step, AgentStep):
                        to_spawn.append((act.task_id, phase_name, pos))
            else:
                pos = executor.initial_position()
                pipe_action, pos = executor.next_action(pos, result=None)
                if isinstance(pipe_action, SpawnAgent):
                    self._state.transition_task(
                        act.task_id,
                        TaskStatus.IN_PROGRESS,
                        phase=Phase(pipe_action.agent),
                    )
                    to_spawn.append((act.task_id, pipe_action.agent, pos))

        return to_spawn

    def _execute_spawns(
        self,
        to_spawn: list[tuple[str, str, PipelinePosition]],
        cycle_num: int,
    ) -> None:
        """Execute spawn operations."""
        # Skip spawning during cooldown (after consecutive failures)
        if to_spawn and self._current_cycle < self._spawn_skip_until:
            return

        for task_id, role, position in to_spawn:
            task = self._state.get_task(task_id)
            branch = task.branch or f"{BRANCH_PREFIX}/{task_id}"
            if task.branch is None:
                self._state.set_task_branch(task_id, branch)
            prompt = self._compose_prompt(task, role, cycle=cycle_num)
            try:
                self._runtime.push_branch(branch)
                handle = self._runtime.spawn(task_id, role, prompt=prompt, branch=branch)
            except Exception:
                self._spawn_failures += 1
                task_fails = self._spawn_task_failures.get(task_id, 0) + 1
                self._spawn_task_failures[task_id] = task_fails
                cooldown_cycles = 0

                if self._spawn_failures >= 3:
                    cooldown_cycles = min(2 ** (self._spawn_failures - 2), 32)
                    self._spawn_skip_until = self._current_cycle + cooldown_cycles

                self._probe.spawn_failed(
                    task_id=task_id,
                    role=role,
                    branch=branch,
                    attempt=task_fails,
                    max_attempts=3,
                    cooldown_cycles=cooldown_cycles,
                    cycle=cycle_num,
                )

                if task_fails >= 3:
                    reason = f"spawn failed 3 times for {role} on branch {branch}"
                    self._state.transition_task(task_id, TaskStatus.FAILED, phase=None)
                    self._probe.task_failed(
                        task_id=task_id,
                        spec_ref=task.spec_ref,
                        reason=reason,
                        round=task.round,
                        cycle=cycle_num,
                    )
                    self._spawn_task_failures.pop(task_id, None)

                if cooldown_cycles:
                    break  # Stop trying more spawns this cycle
                continue

            # Success -- reset counters
            self._spawn_failures = 0
            self._spawn_task_failures.pop(task_id, None)
            self._workers[task_id] = (handle, position, time.monotonic())
            self._probe.worker_spawned(
                task_id=task_id,
                role=role,
                branch=branch,
                round=task.round,
                cycle=cycle_num,
                spec_ref=task.spec_ref,
            )

    # -----------------------------------------------------------------------
    # Convergence check
    # -----------------------------------------------------------------------

    def _check_convergence(self) -> str | None:
        """Check if all tasks are complete/failed. Returns halt reason or None."""
        all_tasks = self._state.get_world().tasks
        if not all_tasks:
            return None

        all_done = all(
            t.status in (TaskStatus.COMPLETE, TaskStatus.FAILED) for t in all_tasks.values()
        )
        if all_done and not self._workers:
            all_complete = all(t.status == TaskStatus.COMPLETE for t in all_tasks.values())
            if all_complete:
                return "all tasks complete"
            return "all tasks resolved (some failed)"
        return None

    # -----------------------------------------------------------------------
    # Serial agents (PM intake)
    # -----------------------------------------------------------------------

    def _unprocessed_specs(self) -> list[str]:
        """Return spec file paths that have no corresponding task."""
        all_specs = self._state.list_files("specs/*.md")
        world = self._state.get_world()
        covered_refs = {task.spec_ref for task in world.tasks.values()}
        return [s for s in all_specs if s not in covered_refs]

    def _collect_cycle_findings(self, reaped_results: dict[str, WorkerResult]) -> str:
        """Collect findings from all failed results this cycle into a single string."""
        sections: list[str] = []
        for task_id, result in reaped_results.items():
            if result.verdict == Verdict.FAIL:
                sections.append(f"### {task_id}\n{result.detail}")
        return "\n\n".join(sections)

    def _run_intake(self) -> None:
        """Run PM intake if there are unprocessed specs."""
        if self._composer is None:
            logger.debug("intake: no composer -- skipping")
            return

        unprocessed = self._unprocessed_specs()
        if not unprocessed:
            logger.debug("intake: no unprocessed specs -- skipping")
            return

        logger.info("intake: %d unprocessed spec(s), running PM", len(unprocessed))

        context = IntakeContext(unprocessed_specs=tuple(unprocessed))
        prompt = self._composer.compose(role="pm", context=context)

        task_count_before = len(self._state.get_world().tasks)
        intake_start = time.monotonic()
        success = self._runtime.run_serial("pm", prompt)

        # Count how many tasks were created by comparing before/after
        task_count_after = len(self._state.get_world().tasks)
        created_count = task_count_after - task_count_before

        self._probe.intake_ran(
            unprocessed_specs=len(unprocessed),
            created_tasks=created_count,
            success=success,
            cycle=self._current_cycle,
            duration_s=time.monotonic() - intake_start,
        )

    # -----------------------------------------------------------------------
    # World building
    # -----------------------------------------------------------------------

    def _build_world(self) -> World:
        """Build a World snapshot including current worker state from runtime."""
        base_world = self._state.get_world()
        workers: dict[str, WorkerState] = {}
        for task_id, (handle, _pos, _spawn_time) in self._workers.items():
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

    # -----------------------------------------------------------------------
    # Prompt composition
    # -----------------------------------------------------------------------

    def _compose_prompt(self, task: Task, role: str, cycle: int) -> str:
        """Compose a prompt for a worker using PromptComposer if available."""
        if self._composer is None:
            return ""

        findings = self._state.get_findings(task.id)
        context = TaskContext(
            task_id=task.id,
            spec_ref=task.spec_ref,
            findings=findings,
            round=task.round,
        )
        prompt = self._composer.compose(
            role=role,
            context=context,
            epilogue=self._runtime.worker_epilogue(),
        )
        self._probe.prompt_composed(
            task_id=task.id,
            role=role,
            prompt_text=prompt,
            round=task.round,
            cycle=cycle,
        )
        return prompt

    # -----------------------------------------------------------------------
    # Pipeline position helpers
    # -----------------------------------------------------------------------

    def _position_from_phase(self, executor: PipelineExecutor, task: Task) -> PipelinePosition:
        """Determine pipeline position from a task's current phase."""
        if task.phase is not None:
            pos = self._find_position_for_role(executor, str(task.phase))
            if pos is not None:
                return pos
        return executor.initial_position()

    @staticmethod
    def _find_position_for_role(executor: PipelineExecutor, role: str) -> PipelinePosition | None:
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

    @staticmethod
    def _find_position_for_step(
        executor: PipelineExecutor, phase_name: str
    ) -> PipelinePosition | None:
        """Walk the pipeline for any step whose name matches phase_name."""

        def _step_name(step: PipelineStep) -> str | None:
            if isinstance(step, AgentStep):
                return step.agent
            if isinstance(step, GateStep):
                return step.gate
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

    def _emit_cycle_completed(
        self,
        cycle_num: int,
        cycle_start: float,
        to_spawn: list[tuple[str, str, PipelinePosition]],
        reaped_results: dict[str, WorkerResult],
    ) -> None:
        """Emit cycle_completed probe event."""
        all_tasks = self._state.get_world().tasks
        self._probe.cycle_completed(
            cycle=cycle_num,
            active_workers=len(self._workers),
            not_started=sum(1 for t in all_tasks.values() if t.status == TaskStatus.NOT_STARTED),
            in_progress=sum(1 for t in all_tasks.values() if t.status == TaskStatus.IN_PROGRESS),
            complete=sum(1 for t in all_tasks.values() if t.status == TaskStatus.COMPLETE),
            failed=sum(1 for t in all_tasks.values() if t.status == TaskStatus.FAILED),
            spawned_ids=tuple(tid for tid, _, _ in to_spawn),
            reaped_ids=tuple(reaped_results.keys()),
            duration_s=time.monotonic() - cycle_start,
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _phase_for_action(action: object) -> str | None:
    """Extract a phase name from a pipeline action (WaitForGate or PerformAction)."""
    if isinstance(action, WaitForGate):
        return action.gate
    if isinstance(action, PerformAction):
        return action.action
    return None


def _phase_for_pipe_action(
    action: SpawnAgent | WaitForGate | PerformAction | PipelineComplete | PipelineFailed,
) -> str | None:
    """Extract a phase name from any pipeline action type."""
    if isinstance(action, SpawnAgent):
        return action.agent
    if isinstance(action, WaitForGate):
        return action.gate
    if isinstance(action, PerformAction):
        return action.action
    return None


def _dep_order_ids(tasks: dict[str, Task], candidate_ids: list[str]) -> list[str]:
    """Return candidate task IDs in topological order: dependencies before dependents.

    Uses Kahn's algorithm (BFS topological sort).
    """
    candidate_set = set(candidate_ids)
    position: dict[str, int] = {cid: i for i, cid in enumerate(candidate_ids)}

    # Build in-degree and adjacency list within the candidate set only
    in_degree: dict[str, int] = {cid: 0 for cid in candidate_ids}
    dependents: dict[str, list[str]] = {cid: [] for cid in candidate_ids}

    for cid in candidate_ids:
        task = tasks.get(cid)
        if task is None:
            continue
        for dep in task.deps:
            if dep in candidate_set:
                in_degree[cid] += 1
                dependents[dep].append(cid)

    queue: list[str] = [cid for cid in candidate_ids if in_degree[cid] == 0]
    result: list[str] = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        newly_ready: list[str] = []
        for dep in dependents[node]:
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                newly_ready.append(dep)
        newly_ready.sort(key=lambda x: position[x])
        queue.extend(newly_ready)

    # Append any remaining cyclic nodes in input order (cycle safety)
    in_result = set(result)
    result.extend(cid for cid in candidate_ids if cid not in in_result)

    return result


def _collect_roles(steps: tuple[PipelineStep, ...]) -> set[str]:
    """Recursively collect all role names from a pipeline."""
    roles: set[str] = set()
    for step in steps:
        if isinstance(step, AgentStep):
            roles.add(step.agent)
        elif isinstance(step, LoopStep):
            roles.update(_collect_roles(step.steps))
    return roles
