"""Orchestrator loop — wires decide, pipeline, state store, and runtime.

Runs the serial section from the spec: reap finished workers, check for halt,
run process-improver/intake, poll gates, merge PRs, decide what to spawn,
update state, spawn workers, and check convergence.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from hyperloop.adapters.probe import NullProbe
from hyperloop.domain.decide import decide
from hyperloop.domain.deps import detect_cycles
from hyperloop.domain.model import (
    ActionStep,
    GateStep,
    Halt,
    ImprovementContext,
    IntakeContext,
    LoopStep,
    Phase,
    PipelinePosition,
    ReapWorker,
    RoleStep,
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
    SpawnRole,
    WaitForGate,
)

if TYPE_CHECKING:
    from hyperloop.compose import PromptComposer
    from hyperloop.domain.model import PipelineStep, Process, Task, WorkerResult
    from hyperloop.ports.pr import PRPort
    from hyperloop.ports.probe import OrchestratorProbe
    from hyperloop.ports.runtime import Runtime
    from hyperloop.ports.state import StateStore

logger: structlog.stdlib.BoundLogger = structlog.get_logger()

BRANCH_PREFIX = "hyperloop"


class Orchestrator:
    """Main orchestrator loop — one serial section per cycle.

    The orchestrator tracks active workers and their pipeline positions.
    Each cycle follows the spec's serial section order:
      1. Reap finished workers
      2. Halt if any task failed
      3. Process-improver (serial on trunk)
      4. Intake (serial on trunk)
      5. Poll gates
      6. Merge ready PRs
      7. Decide what to spawn (via decide())
      8. Update state (transition tasks, commit)
      9. Spawn workers
    """

    def __init__(
        self,
        state: StateStore,
        runtime: Runtime,
        process: Process,
        max_workers: int = 6,
        max_task_rounds: int = 50,
        pr_manager: PRPort | None = None,
        composer: PromptComposer | None = None,
        repo_path: str | None = None,
        poll_interval: float = 30.0,
        probe: OrchestratorProbe | None = None,
        max_rebase_attempts: int = 3,
        auto_merge: bool = True,
    ) -> None:
        self._state = state
        self._runtime = runtime
        self._process = process
        self._max_workers = max_workers
        self._max_task_rounds = max_task_rounds
        self._pr_manager = pr_manager
        self._composer = composer
        self._repo_path = repo_path
        self._poll_interval = poll_interval
        self._probe = probe or NullProbe()
        self._max_rebase_attempts = max_rebase_attempts
        self._auto_merge = auto_merge

        # Active worker tracking: task_id -> (handle, pipeline_position, spawn_time)
        self._workers: dict[str, tuple[WorkerHandle, PipelinePosition, float]] = {}
        # Consecutive rebase failure count per task
        self._rebase_attempts: dict[str, int] = {}
        # Current cycle number — set at the start of each run_cycle
        self._current_cycle: int = 0
        # Spawn backoff: global consecutive failures + per-task retry counts
        self._spawn_failures: int = 0
        self._spawn_skip_until: int = 0
        self._spawn_task_failures: dict[str, int] = {}

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
        roles.update(_collect_roles(self._process.intake))
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

            # We don't add to _workers here — instead leave it workerless
            # so decide() will emit a SpawnWorker for it next cycle.
            logger.info(
                "recover: task %s is IN_PROGRESS at phase %s, will re-spawn",
                task.id,
                task.phase,
            )

    def run_cycle(self, cycle_num: int = 0) -> str | None:
        """Run one serial section cycle.

        Returns a halt reason string if the loop should stop, or None to continue.
        """
        self._current_cycle = cycle_num
        cycle_start = time.monotonic()
        executor = PipelineExecutor(self._process.pipeline)

        # Cache world snapshot once per cycle — augmented with worker state
        world = self._build_world()

        # ---- 0. Early exit on zero tasks -------------------------------------
        if not world.tasks and not self._workers:
            # Try intake first — it may create tasks from new specs
            self._run_intake()
            world = self._build_world()
            if not world.tasks and not self._workers:
                reason = "no tasks found — nothing to do"
                return reason

        self._probe.cycle_started(
            cycle=cycle_num,
            active_workers=len(self._workers),
            not_started=sum(1 for t in world.tasks.values() if t.status == TaskStatus.NOT_STARTED),
            in_progress=sum(1 for t in world.tasks.values() if t.status == TaskStatus.IN_PROGRESS),
            complete=sum(1 for t in world.tasks.values() if t.status == TaskStatus.COMPLETE),
            failed=sum(1 for t in world.tasks.values() if t.status == TaskStatus.FAILED),
        )

        # ---- 1. Reap finished workers ----------------------------------------
        reaped_results: dict[str, WorkerResult] = {}
        had_failures_this_cycle = False

        actions = decide(world, self._max_workers, self._max_task_rounds)

        # Process ReapWorker actions from decide()
        for action in actions:
            if isinstance(action, ReapWorker):
                task_id = action.task_id
                if task_id in self._workers:
                    handle, _pos, _spawn_time = self._workers[task_id]
                    result = self._runtime.reap(handle)
                    reaped_results[task_id] = result

        # ---- 2. Process reaped results through pipeline ----------------------
        to_spawn: list[tuple[str, str, PipelinePosition]] = []
        halt_reason: str | None = None

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
                findings_count=result.findings,
                detail=result.detail,
                duration_s=time.monotonic() - spawn_time,
                cost_usd=result.cost_usd,
                num_turns=result.num_turns,
                api_duration_ms=result.api_duration_ms,
            )

            pipe_action, new_pos = executor.next_action(position, result)

            if isinstance(pipe_action, PipelineComplete):
                # Mark PR ready if reviews passed and pipeline is done
                if self._pr_manager is not None and task.pr is not None:
                    self._pr_manager.mark_ready(task.pr)
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
                    findings_count=result.findings,
                    detail=result.detail,
                )
                halt_reason = f"task {task_id} pipeline failed: {pipe_action.reason}"
                had_failures_this_cycle = True
                self._probe.task_failed(
                    task_id=task_id,
                    spec_ref=task.spec_ref,
                    reason=pipe_action.reason,
                    round=task.round,
                    cycle=cycle_num,
                )

            elif isinstance(pipe_action, SpawnRole):
                if result.verdict in (Verdict.FAIL, Verdict.ERROR, Verdict.TIMEOUT):
                    had_failures_this_cycle = True
                    new_round = task.round + 1
                    if new_round >= self._max_task_rounds:
                        self._state.transition_task(
                            task_id,
                            TaskStatus.FAILED,
                            phase=None,
                            round=new_round,
                        )
                        halt_reason = (
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
                        findings_count=result.findings,
                        detail=result.detail,
                    )
                    self._state.transition_task(
                        task_id,
                        TaskStatus.IN_PROGRESS,
                        phase=Phase(pipe_action.role),
                        round=new_round,
                    )
                    self._probe.task_looped_back(
                        task_id=task_id,
                        spec_ref=task.spec_ref,
                        round=new_round,
                        cycle=cycle_num,
                        findings_preview=result.detail[:200],
                        findings_count=result.findings,
                    )
                else:
                    # Advancing forward on PASS — create draft PR if needed
                    if self._pr_manager is not None and task.pr is None:
                        branch = task.branch or f"{BRANCH_PREFIX}/{task_id}"
                        pr_url = self._pr_manager.create_draft(
                            task_id, branch, task.title, task.spec_ref
                        )
                        if pr_url:
                            self._state.set_task_pr(task_id, pr_url)

                    self._state.transition_task(
                        task_id,
                        TaskStatus.IN_PROGRESS,
                        phase=Phase(pipe_action.role),
                    )
                    self._probe.task_advanced(
                        task_id=task_id,
                        spec_ref=task.spec_ref,
                        from_phase=str(task.phase) if task.phase else None,
                        to_phase=pipe_action.role,
                        from_status=task.status.value,
                        to_status=TaskStatus.IN_PROGRESS.value,
                        round=task.round,
                        cycle=cycle_num,
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

        # ---- 2b. Halt if any task failed -------------------------------------
        if halt_reason is not None:
            self._state.commit("orchestrator: halt")
            return halt_reason

        # ---- 3. Process-improver ------------------------------------------------
        if had_failures_this_cycle:
            self._run_process_improver(reaped_results)

        # ---- 4. Intake ----------------------------------------------------------
        self._run_intake()

        # ---- 5. Poll gates ---------------------------------------------------
        self._poll_gates(executor, to_spawn)

        # ---- 6. Merge ready PRs ----------------------------------------------
        # Commit state before merge — local merge does git checkout which
        # fails if there are uncommitted changes to task files on trunk.
        self._state.commit("orchestrator: pre-merge state")
        self._merge_ready_prs()

        # ---- 7. Decide what to spawn (via decide()) -------------------------
        # Rebuild world after reaping + gates + merges (tasks may have changed)
        world_after_reap = self._build_world()
        spawn_actions = decide(world_after_reap, self._max_workers, self._max_task_rounds)

        # Check for Halt from decide() (convergence or max_task_rounds)
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
                    pos = executor.initial_position()
                    self._state.transition_task(
                        action.task_id,
                        TaskStatus.IN_PROGRESS,
                        phase=Phase("rebase-resolver"),
                    )
                    to_spawn.append((action.task_id, "rebase-resolver", pos))
                elif task.status == TaskStatus.IN_PROGRESS and task.phase is not None:
                    # Only spawn for role steps — gates and actions wait, not spawn
                    phase_name = str(task.phase)
                    pos = self._find_position_for_step(executor, phase_name)
                    if pos is not None:
                        step = PipelineExecutor.resolve_step(executor.pipeline, pos.path)
                        if isinstance(step, RoleStep):
                            to_spawn.append((action.task_id, phase_name, pos))
                else:
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
        # Skip spawning during cooldown (after consecutive failures)
        if to_spawn and self._current_cycle < self._spawn_skip_until:
            to_spawn = []

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

            # Success — reset counters
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

        # ---- Check convergence -----------------------------------------------
        all_tasks = self._state.get_world().tasks
        if not all_tasks:
            self._emit_cycle_completed(cycle_num, cycle_start, to_spawn, reaped_results)
            return None

        self._emit_cycle_completed(cycle_num, cycle_start, to_spawn, reaped_results)
        return None

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

    # -----------------------------------------------------------------------
    # Gate polling and merge
    # -----------------------------------------------------------------------

    def _poll_gates(
        self,
        executor: PipelineExecutor,
        to_spawn: list[tuple[str, str, PipelinePosition]],
    ) -> None:
        """Poll gates for tasks at a gate step. If cleared, advance the task."""
        if self._pr_manager is None:
            logger.debug("gates: no PRManager — skipping gate polling")
            return

        all_tasks = self._state.get_world().tasks
        for task in all_tasks.values():
            if task.status != TaskStatus.IN_PROGRESS:
                continue
            if task.phase is None:
                continue

            # Check if this phase corresponds to a gate step in the pipeline
            pos = self._find_position_for_step(executor, str(task.phase))
            if pos is None:
                continue

            step = PipelineExecutor.resolve_step(executor.pipeline, pos.path)
            if not isinstance(step, GateStep):
                continue

            # Ensure the task has a PR — create one if missing (e.g. previous crash)
            if task.pr is None:
                branch = task.branch or f"{BRANCH_PREFIX}/{task.id}"
                pr_url = self._pr_manager.create_draft(task.id, branch, task.title, task.spec_ref)
                if pr_url:
                    self._state.set_task_pr(task.id, pr_url)
                    task = self._state.get_task(task.id)
                else:
                    continue  # Can't poll gate without a PR

            # Check PR state — handle closed/merged PRs before polling
            pr_state = self._pr_manager.get_pr_state(task.pr)
            if pr_state is not None and pr_state.state == "MERGED":
                # Someone merged the PR manually — all remaining steps are done
                self._probe.merge_attempted(
                    task_id=task.id,
                    branch=task.branch or f"{BRANCH_PREFIX}/{task.id}",
                    spec_ref=task.spec_ref,
                    outcome="merged_externally",
                    attempt=0,
                    cycle=self._current_cycle,
                )
                self._state.transition_task(task.id, TaskStatus.COMPLETE, phase=None)
                continue

            if pr_state is not None and pr_state.state == "CLOSED":
                # PR was closed — create a new one so humans can review/approve
                branch = task.branch or f"{BRANCH_PREFIX}/{task.id}"
                new_url = self._pr_manager.create_draft(task.id, branch, task.title, task.spec_ref)
                if new_url:
                    self._state.set_task_pr(task.id, new_url)
                    task = self._state.get_task(task.id)
                else:
                    continue

            # Task is at a gate — poll it
            cleared = self._pr_manager.check_gate(task.pr, step.gate)
            self._probe.gate_checked(
                task_id=task.id,
                gate=step.gate,
                cleared=cleared,
                cycle=self._current_cycle,
            )
            if not cleared:
                continue
            advanced = PipelineExecutor.advance_from(executor.pipeline, pos.path)
            if advanced is not None:
                next_action, new_pos = advanced
                phase_name = _phase_for_pipe_action(next_action)
                self._state.transition_task(
                    task.id,
                    TaskStatus.IN_PROGRESS,
                    phase=Phase(phase_name) if phase_name else None,
                )
                if isinstance(next_action, SpawnRole):
                    to_spawn.append((task.id, next_action.role, new_pos))
            else:
                self._state.transition_task(task.id, TaskStatus.COMPLETE, phase=None)

    def _merge_ready_prs(self) -> None:
        """Merge branches for tasks at the merge-pr action step.

        Tasks are merged in dependency order (deps before dependents) to avoid
        unnecessary rebase conflicts and produce a correct merge history.
        Within the same dependency tier, tasks are merged in task-ID order for
        determinism.

        With a PRManager: rebase + squash-merge the PR.
        Without a PRManager: local git merge of worker branch into base branch.
        On conflict, transitions to NEEDS_REBASE.

        If auto_merge is False, skip merging entirely — the PR stays ready
        for human merge.
        """
        if not self._auto_merge:
            logger.debug("auto_merge disabled — skipping merge step")
            return

        all_tasks = self._state.get_world().tasks

        # Collect candidates at merge-pr, sorted by task ID for stable tiebreaking
        candidate_ids = sorted(
            task_id
            for task_id, task in all_tasks.items()
            if task.status == TaskStatus.IN_PROGRESS and task.phase == Phase("merge-pr")
        )

        # Apply topological ordering so dependencies merge before dependents
        ordered_ids = _dep_order_ids(all_tasks, candidate_ids)

        for task_id in ordered_ids:
            task = all_tasks[task_id]
            branch = task.branch or f"{BRANCH_PREFIX}/{task.id}"

            if self._pr_manager is not None and task.pr is not None:
                self._merge_via_pr(task.id, task.pr, task.spec_ref, branch)
            else:
                self._merge_local(task.id, branch, task.spec_ref)

    def _merge_via_pr(self, task_id: str, pr_url: str, spec_ref: str, branch: str) -> None:
        """Merge via GitHub PR: mark ready, rebase, then squash-merge.

        Checks PR state first to handle PRs that were closed or merged
        externally (by a human).  For MERGED PRs, verifies that the
        branch tip matches what was merged — if not, there is unmerged
        work and a new PR is created.
        """
        assert self._pr_manager is not None

        # ---- Check PR state before operating on it --------------------------
        pr_state = self._pr_manager.get_pr_state(pr_url)

        if pr_state is None:
            self._probe.merge_attempted(
                task_id=task_id,
                branch=branch,
                spec_ref=spec_ref,
                outcome="pr_not_found",
                attempt=0,
                cycle=self._current_cycle,
            )
            return

        if pr_state.state == "MERGED":
            # Verify all work is on trunk by comparing merge head to branch tip
            branch_tip = self._get_branch_tip(branch)
            if branch_tip is None or pr_state.head_sha == branch_tip:
                # All work captured (or branch deleted) — mark complete
                self._rebase_attempts.pop(task_id, None)
                self._state.transition_task(task_id, TaskStatus.COMPLETE, phase=None)
                self._probe.merge_attempted(
                    task_id=task_id,
                    branch=branch,
                    spec_ref=spec_ref,
                    outcome="merged_externally",
                    attempt=0,
                    cycle=self._current_cycle,
                )
                return
            # Branch has commits beyond what was merged — create new PR
            self._probe.merge_attempted(
                task_id=task_id,
                branch=branch,
                spec_ref=spec_ref,
                outcome="stale_merge",
                attempt=0,
                cycle=self._current_cycle,
            )
            pr_url = self._recreate_pr(task_id, branch, spec_ref)
            if not pr_url:
                return

        elif pr_state.state == "CLOSED":
            self._probe.merge_attempted(
                task_id=task_id,
                branch=branch,
                spec_ref=spec_ref,
                outcome="pr_closed",
                attempt=0,
                cycle=self._current_cycle,
            )
            pr_url = self._recreate_pr(task_id, branch, spec_ref)
            if not pr_url:
                return

        # ---- PR is OPEN — proceed with normal merge flow --------------------
        self._pr_manager.mark_ready(pr_url)

        if not self._pr_manager.rebase_branch(branch, "main"):
            self._handle_rebase_failure(task_id, branch)
            return

        if not self._pr_manager.wait_mergeable(pr_url):
            self._handle_rebase_failure(task_id, branch)
            return

        if not self._pr_manager.merge(pr_url, task_id, spec_ref):
            self._handle_rebase_failure(task_id, branch)
            return

        # Merge succeeded — reset counter, remove gate label
        self._rebase_attempts.pop(task_id, None)
        self._pr_manager.remove_gate_label(pr_url)
        self._state.transition_task(task_id, TaskStatus.COMPLETE, phase=None)
        self._probe.merge_attempted(
            task_id=task_id,
            branch=branch,
            spec_ref=spec_ref,
            outcome="merged",
            attempt=0,
            cycle=self._current_cycle,
        )

    def _recreate_pr(self, task_id: str, branch: str, spec_ref: str) -> str:
        """Create a new draft PR for a task, updating state. Returns URL or ""."""
        assert self._pr_manager is not None
        task = self._state.get_task(task_id)
        new_url = self._pr_manager.create_draft(task_id, branch, task.title, spec_ref)
        if not new_url:
            logger.warning("Failed to create replacement PR for task %s", task_id)
            return ""
        self._state.set_task_pr(task_id, new_url)
        return new_url

    def _get_branch_tip(self, branch: str) -> str | None:
        """Return the SHA of a remote branch tip, or None if not found.

        Fetches from origin first to ensure the tracking ref is current.
        """
        import subprocess

        git_cmd = ["git"]
        if self._repo_path is not None:
            git_cmd = ["git", "-C", self._repo_path]

        # Fetch to ensure tracking ref is up to date
        subprocess.run(
            [*git_cmd, "fetch", "origin", branch],
            capture_output=True,
            text=True,
        )

        result = subprocess.run(
            [*git_cmd, "rev-parse", f"origin/{branch}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def _handle_rebase_failure(self, task_id: str, branch: str) -> None:
        """Handle a rebase or merge conflict — track attempts, loop back if needed."""
        logger.warning("Rebase/merge conflict for task %s, marking NEEDS_REBASE", task_id)
        self._rebase_attempts[task_id] = self._rebase_attempts.get(task_id, 0) + 1
        looping_back = self._rebase_attempts[task_id] >= self._max_rebase_attempts
        self._probe.rebase_conflict(
            task_id=task_id,
            branch=branch,
            attempt=self._rebase_attempts[task_id],
            max_attempts=self._max_rebase_attempts,
            looping_back=looping_back,
            cycle=self._current_cycle,
        )
        if looping_back:
            logger.warning(
                "Task %s exceeded max_rebase_attempts (%d), looping back",
                task_id,
                self._max_rebase_attempts,
            )
            self._rebase_attempts.pop(task_id, None)
            task = self._state.get_task(task_id)
            detail = f"Rebase conflict after {self._max_rebase_attempts} attempts"
            self._state.store_review(
                task_id,
                round=task.round,
                role="orchestrator",
                verdict="fail",
                findings_count=1,
                detail=detail,
            )
            self._state.transition_task(
                task_id,
                TaskStatus.IN_PROGRESS,
                phase=Phase("implementer"),
                round=task.round + 1,
            )
            return
        self._state.transition_task(task_id, TaskStatus.NEEDS_REBASE, phase=Phase("merge-pr"))

    def _merge_local(self, task_id: str, branch: str, spec_ref: str) -> None:
        """Merge worker branch into base branch locally (no PR).

        Uses --no-commit so we can resolve .hyperloop/state/ conflicts
        before finalizing.  The orchestrator owns task state files
        (.hyperloop/state/tasks/) — on conflict those always take the
        trunk version.  Review files (.hyperloop/state/reviews/) are
        worker output — on conflict those take the branch version.
        Non-state conflicts are real and trigger NEEDS_REBASE.
        """
        import subprocess

        git_cmd = ["git"]
        if self._repo_path is not None:
            git_cmd = ["git", "-C", self._repo_path]

        merge_result = subprocess.run(
            [*git_cmd, "merge", branch, "--no-commit", "--no-ff"],
            capture_output=True,
            text=True,
        )

        if merge_result.returncode != 0 and not self._resolve_state_conflicts(git_cmd, branch):
            # Non-state conflicts exist — abort and handle normally
            subprocess.run(
                [*git_cmd, "merge", "--abort"],
                capture_output=True,
                check=False,
            )
            self._handle_local_merge_conflict(task_id, branch, git_cmd)
            return

        # Restore trunk's version of task state files (orchestrator owns these)
        subprocess.run(
            [*git_cmd, "checkout", "HEAD", "--", ".hyperloop/state/tasks/"],
            capture_output=True,
        )
        # Ensure review files from the branch are kept (worker output)
        subprocess.run(
            [*git_cmd, "checkout", branch, "--", ".hyperloop/state/reviews/"],
            capture_output=True,
        )
        # Stage any changes from the checkout resolutions
        subprocess.run(
            [*git_cmd, "add", ".hyperloop/state/"],
            capture_output=True,
        )

        # Commit the merge
        try:
            subprocess.run(
                [*git_cmd, "commit", "--no-edit", "-m", f"merge: {task_id}"],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            # Commit failed (e.g. nothing to commit, branch missing) — abort
            subprocess.run(
                [*git_cmd, "merge", "--abort"],
                capture_output=True,
                check=False,
            )
            self._handle_local_merge_conflict(task_id, branch, git_cmd)
            return

        self._rebase_attempts.pop(task_id, None)
        self._state.transition_task(task_id, TaskStatus.COMPLETE, phase=None)
        self._delete_local_branch(branch)
        self._probe.merge_attempted(
            task_id=task_id,
            branch=branch,
            spec_ref=spec_ref,
            outcome="merged",
            attempt=0,
            cycle=self._current_cycle,
        )
        logger.info("Local merge of %s into base branch", task_id)

    def _resolve_state_conflicts(self, git_cmd: list[str], branch: str) -> bool:
        """Attempt to resolve conflicts limited to .hyperloop/state/.

        Returns True if all conflicts were in .hyperloop/state/ and have
        been resolved.  Returns False if any non-state file has a conflict
        (caller should abort the merge).
        """
        import subprocess

        # List conflicted files
        result = subprocess.run(
            [*git_cmd, "diff", "--name-only", "--diff-filter=U"],
            capture_output=True,
            text=True,
        )
        conflicted = [f for f in result.stdout.strip().splitlines() if f]

        if not conflicted:
            return True

        for path in conflicted:
            if path.startswith(".hyperloop/state/tasks/"):
                # Orchestrator owns task state — take trunk (ours)
                subprocess.run(
                    [*git_cmd, "checkout", "--ours", "--", path],
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    [*git_cmd, "add", path],
                    check=True,
                    capture_output=True,
                )
            elif path.startswith(".hyperloop/state/reviews/"):
                # Worker output — take branch (theirs)
                subprocess.run(
                    [*git_cmd, "checkout", "--theirs", "--", path],
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    [*git_cmd, "add", path],
                    check=True,
                    capture_output=True,
                )
            elif path.startswith(".hyperloop/state/"):
                # Other state files — take trunk (ours) by default
                subprocess.run(
                    [*git_cmd, "checkout", "--ours", "--", path],
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    [*git_cmd, "add", path],
                    check=True,
                    capture_output=True,
                )
            else:
                # Non-state conflict — cannot auto-resolve
                return False

        return True

    def _handle_local_merge_conflict(self, task_id: str, branch: str, git_cmd: list[str]) -> None:
        """Handle a local merge conflict — increment rebase counter or loop back."""
        logger.warning("Local merge conflict for task %s, marking NEEDS_REBASE", task_id)
        self._rebase_attempts[task_id] = self._rebase_attempts.get(task_id, 0) + 1
        looping_back = self._rebase_attempts[task_id] >= self._max_rebase_attempts
        self._probe.rebase_conflict(
            task_id=task_id,
            branch=branch,
            attempt=self._rebase_attempts[task_id],
            max_attempts=self._max_rebase_attempts,
            looping_back=looping_back,
            cycle=self._current_cycle,
        )
        if looping_back:
            logger.warning(
                "Task %s exceeded max_rebase_attempts (%d), looping back",
                task_id,
                self._max_rebase_attempts,
            )
            self._rebase_attempts.pop(task_id, None)
            task = self._state.get_task(task_id)
            detail = f"Merge conflict after {self._max_rebase_attempts} attempts"
            self._state.store_review(
                task_id,
                round=task.round,
                role="orchestrator",
                verdict="fail",
                findings_count=1,
                detail=detail,
            )
            self._state.transition_task(
                task_id,
                TaskStatus.IN_PROGRESS,
                phase=Phase("implementer"),
                round=task.round + 1,
            )
            return
        self._state.transition_task(task_id, TaskStatus.NEEDS_REBASE, phase=Phase("merge-pr"))

    def _delete_local_branch(self, branch: str) -> None:
        """Delete a local branch after merge (best-effort)."""
        import subprocess

        git_cmd = ["git"]
        if self._repo_path is not None:
            git_cmd = ["git", "-C", self._repo_path]
        subprocess.run([*git_cmd, "branch", "-D", branch], capture_output=True)

    # -----------------------------------------------------------------------
    # Serial agents (PM intake + process-improver)
    # -----------------------------------------------------------------------

    def _unprocessed_specs(self) -> list[str]:
        """Return spec file paths that have no corresponding task.

        Scans specs/*.md (product specs only — tasks and reviews live under
        .hyperloop/state/) and checks whether any existing task references
        each spec via its spec_ref field.
        """
        all_specs = self._state.list_files("specs/*.md")
        world = self._state.get_world()
        covered_refs = {task.spec_ref for task in world.tasks.values()}
        return [s for s in all_specs if s not in covered_refs]

    def _collect_cycle_findings(self, reaped_results: dict[str, WorkerResult]) -> str:
        """Collect findings from all failed results this cycle into a single string."""
        sections: list[str] = []
        for task_id, result in reaped_results.items():
            if result.verdict in (Verdict.FAIL, Verdict.ERROR, Verdict.TIMEOUT):
                sections.append(f"### {task_id}\n{result.detail}")
        return "\n\n".join(sections)

    def _run_intake(self) -> None:
        """Run PM intake if there are unprocessed specs."""
        if self._composer is None:
            logger.debug("intake: no composer — skipping")
            return

        unprocessed = self._unprocessed_specs()
        if not unprocessed:
            logger.debug("intake: no unprocessed specs — skipping")
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

    def _run_process_improver(self, reaped_results: dict[str, WorkerResult]) -> None:
        """Run process-improver with findings from failed results this cycle."""
        if self._composer is None:
            logger.info("process-improver: no composer — skipping")
            return

        findings_text = self._collect_cycle_findings(reaped_results)
        if not findings_text:
            logger.debug("process-improver: no failure findings this cycle — skipping")
            return

        logger.info("process-improver: running with this cycle's findings")

        context = ImprovementContext(findings=findings_text)
        prompt = self._composer.compose(role="process-improver", context=context)

        failed_ids = tuple(
            task_id
            for task_id, r in reaped_results.items()
            if r.verdict in (Verdict.FAIL, Verdict.ERROR, Verdict.TIMEOUT)
        )

        improver_start = time.monotonic()
        success = self._runtime.run_serial("process-improver", prompt)
        self._probe.process_improver_ran(
            failed_task_ids=failed_ids,
            success=success,
            cycle=self._current_cycle,
            duration_s=time.monotonic() - improver_start,
        )
        if success:
            # Re-resolve templates so agents spawned after this point
            # see updated guidelines (mechanical guarantee from spec).
            self._composer.rebuild()

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
            task_id=task.id, spec_ref=task.spec_ref, findings=findings, round=task.round
        )
        prompt = self._composer.compose(
            role=role, context=context, epilogue=self._runtime.worker_epilogue()
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
        """Walk the pipeline for a RoleStep matching the given role name."""

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

        return _search(executor.pipeline, ())

    @staticmethod
    def _find_position_for_step(
        executor: PipelineExecutor, phase_name: str
    ) -> PipelinePosition | None:
        """Walk the pipeline for any step whose name matches phase_name.

        Searches depth-first across RoleStep, GateStep, and ActionStep.
        """

        def _step_name(step: PipelineStep) -> str | None:
            if isinstance(step, RoleStep):
                return step.role
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
    action: SpawnRole | WaitForGate | PerformAction | PipelineComplete | PipelineFailed,
) -> str | None:
    """Extract a phase name from any pipeline action type."""
    if isinstance(action, SpawnRole):
        return action.role
    if isinstance(action, WaitForGate):
        return action.gate
    if isinstance(action, PerformAction):
        return action.action
    return None


def _dep_order_ids(tasks: dict[str, Task], candidate_ids: list[str]) -> list[str]:
    """Return candidate task IDs in topological order: dependencies before dependents.

    Uses Kahn's algorithm (BFS topological sort).

    - Only considers dependencies within the candidate set; tasks outside
      candidates are treated as already merged/done.
    - Preserves input order for tasks with no dependency relationship
      (callers pre-sort by task ID for determinism).
    - Falls back to input order for any cyclic group (cycle safety).
    - Candidates missing from the tasks dict are included unchanged (graceful).
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

    # Kahn's BFS: start with zero in-degree nodes in input order.
    # list.pop(0) is O(n) but candidate counts are always tiny.
    queue: list[str] = [cid for cid in candidate_ids if in_degree[cid] == 0]
    result: list[str] = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        # Collect newly-ready dependents and sort by input position for stability
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
        if isinstance(step, RoleStep):
            roles.add(step.role)
        elif isinstance(step, LoopStep):
            roles.update(_collect_roles(step.steps))
    return roles
