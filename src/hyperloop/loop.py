"""Orchestrator loop -- thin coordinator that delegates to cycle phases.

Runs a 4-phase cycle: COLLECT, INTAKE, ADVANCE, SPAWN.
Each phase returns a result dataclass; the Orchestrator applies mutations.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from hyperloop.adapters.notification.null import NullNotification
from hyperloop.adapters.probe import NullProbe
from hyperloop.cycle import (
    BRANCH_PREFIX,
    advance,
    collect,
    collect_roles,
    collect_steps_of_type,
    plan_spawns,
    run_intake,
)
from hyperloop.cycle.helpers import build_world
from hyperloop.cycle.intake import _detect_spec_entries
from hyperloop.domain.deps import detect_cycles
from hyperloop.domain.model import (
    ActionStep,
    CheckStep,
    GateStep,
    PipelinePosition,
    TaskContext,
    TaskStatus,
    Verdict,
    WorkerHandle,
)
from hyperloop.domain.pipeline import PipelineExecutor

if TYPE_CHECKING:
    from hyperloop.compose import PromptComposer
    from hyperloop.cycle.intake import IntakeResult
    from hyperloop.cycle.spawn import SpawnPlan
    from hyperloop.domain.model import Process, Task, WorkerResult
    from hyperloop.ports.action import ActionPort
    from hyperloop.ports.check import CheckPort
    from hyperloop.ports.gate import GatePort
    from hyperloop.ports.hook import CycleHook
    from hyperloop.ports.notification import NotificationPort
    from hyperloop.ports.pr import PRPort
    from hyperloop.ports.probe import OrchestratorProbe
    from hyperloop.ports.runtime import Runtime
    from hyperloop.ports.spec_source import SpecSource
    from hyperloop.ports.state import StateStore

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


class Orchestrator:
    """Thin coordinator: delegates to cycle phases, applies their results."""

    def __init__(
        self,
        state: StateStore,
        runtime: Runtime,
        process: Process,
        max_workers: int = 6,
        max_task_rounds: int = 50,
        max_action_attempts: int = 3,
        base_branch: str = "main",
        gate: GatePort | None = None,
        action: ActionPort | None = None,
        check: CheckPort | None = None,
        pr: PRPort | None = None,
        spec_source: SpecSource | None = None,
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
        self._base_branch = base_branch
        self._gate = gate
        self._action = action
        self._check = check
        self._pr = pr
        self._spec_source = spec_source
        self._hooks = hooks
        self._notification: NotificationPort = notification or NullNotification()
        self._composer = composer
        self._poll_interval = poll_interval
        self._probe: OrchestratorProbe = probe or NullProbe()

        self._workers: dict[str, tuple[WorkerHandle, PipelinePosition, float]] = {}
        self._action_attempts: dict[str, int] = {}
        self._current_cycle: int = 0
        self._spawn_failures: int = 0
        self._spawn_skip_until: int = 0
        self._spawn_task_failures: dict[str, int] = {}
        self._notified_gates: set[str] = set()
        self._has_failures_since_intake: bool = False

    def validate_templates(self) -> None:
        """Validate that every role in the pipeline has a resolved template."""
        if self._composer is None:
            return
        roles = collect_roles(self._process.pipeline)
        missing = [r for r in roles if r not in self._composer._templates]
        if missing:
            msg = (
                f"Pipeline references roles with no agent template: {sorted(missing)}. "
                "Check that base/ has definitions for these roles and "
                "kustomize build resolves them."
            )
            raise ValueError(msg)

    def validate_ports(self) -> None:
        """Validate that pipeline steps have matching port adapters."""
        gates = collect_steps_of_type(self._process.pipeline, GateStep)
        actions = collect_steps_of_type(self._process.pipeline, ActionStep)
        checks = collect_steps_of_type(self._process.pipeline, CheckStep)
        if gates and self._gate is None:
            names = sorted({s.gate for s in gates})  # type: ignore[union-attr]
            raise ValueError(
                f"Pipeline has gate steps {names} but no gate adapter is configured. "
                "Set --repo to enable PR-based gates, or remove gate steps from the pipeline."
            )
        if actions and self._action is None:
            names = sorted({s.action for s in actions})  # type: ignore[union-attr]
            raise ValueError(
                f"Pipeline has action steps {names} but no action adapter is configured. "
                "Set --repo to enable PR-based actions, or remove action steps from the pipeline."
            )
        if checks and self._check is None:
            names = sorted({s.check for s in checks})  # type: ignore[union-attr]
            raise ValueError(
                f"Pipeline has check steps {names} but no check adapter is configured. "
                "Set --repo to enable PR-based checks, or remove check steps from the pipeline."
            )

    def run_loop(self, max_cycles: int = 200) -> str:
        """Run the orchestrator loop until halt or max_cycles."""
        self.validate_templates()
        self.validate_ports()
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

    def recover(self) -> None:
        """Recover from a crash by reconciling persisted state with runtime."""
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
            if task.status != TaskStatus.IN_PROGRESS or task.id in self._workers:
                continue
            branch = task.branch or f"{BRANCH_PREFIX}/{task.id}"
            orphan = self._runtime.find_orphan(task.id, branch)
            if orphan is not None:
                self._runtime.cancel(orphan)
                self._probe.orphan_found(task_id=task.id, branch=branch)
            logger.info("recover: task %s at phase %s, will re-spawn", task.id, task.phase)

    def run_cycle(self, cycle_num: int = 0) -> str | None:
        """Run one 4-phase cycle. Returns halt reason or None."""
        self._current_cycle = cycle_num
        cycle_start = time.monotonic()
        executor = PipelineExecutor(self._process.pipeline)

        # Early exit on zero tasks
        world = build_world(self._workers, self._state, self._runtime)
        if not world.tasks and not self._workers:
            self._apply_intake(
                run_intake(
                    self._state,
                    self._runtime,
                    self._composer,
                    self._has_failures_since_intake,
                    spec_source=self._spec_source,
                )
            )
            world = build_world(self._workers, self._state, self._runtime)
            if not world.tasks and not self._workers:
                return "no tasks found -- nothing to do"

        self._probe.cycle_started(
            cycle=cycle_num,
            active_workers=len(self._workers),
            not_started=sum(1 for t in world.tasks.values() if t.status == TaskStatus.NOT_STARTED),
            in_progress=sum(1 for t in world.tasks.values() if t.status == TaskStatus.IN_PROGRESS),
            complete=sum(1 for t in world.tasks.values() if t.status == TaskStatus.COMPLETE),
            failed=sum(1 for t in world.tasks.values() if t.status == TaskStatus.FAILED),
        )

        # COLLECT
        collected = collect(
            workers=self._workers,
            state=self._state,
            runtime=self._runtime,
            probe=self._probe,
            max_workers=self._max_workers,
            max_task_rounds=self._max_task_rounds,
            cycle=cycle_num,
        )
        self._workers = collected.remaining_workers
        if any(r.verdict == Verdict.FAIL for r in collected.reaped.values()):
            self._has_failures_since_intake = True
        if collected.reaped:
            for hook in self._hooks:
                hook.after_reap(results=collected.reaped, cycle=cycle_num)

        # INTAKE
        self._apply_intake(
            run_intake(self._state, self._runtime, self._composer, self._has_failures_since_intake)
        )

        # ADVANCE
        advanced = advance(
            state=self._state,
            reaped=collected.reaped,
            reaped_metadata=collected.reaped_metadata,
            executor=executor,
            gate=self._gate,
            action=self._action,
            check=self._check,
            pr=self._pr,
            notification=self._notification,
            probe=self._probe,
            max_task_rounds=self._max_task_rounds,
            max_action_attempts=self._max_action_attempts,
            action_attempts=dict(self._action_attempts),
            notified_gates=set(self._notified_gates),
            cycle=cycle_num,
            running_tasks=frozenset(self._workers.keys()),
        )
        for t in advanced.transitions:
            if t.reset_branch:
                # Poisoned branch — delete remote branch and reset task
                task = self._state.get_task(t.task_id)
                if task.branch is not None:
                    self._delete_remote_branch(task.branch)
                self._state.reset_task(t.task_id)
            else:
                self._state.transition_task(t.task_id, t.status, t.phase, t.round)
            if t.review is not None:
                self._state.store_review(
                    t.task_id, t.review.round, t.review.role, t.review.verdict, t.review.detail
                )
            if t.pr_url is not None:
                self._state.set_task_pr(t.task_id, t.pr_url)
        self._action_attempts = advanced.action_attempts
        self._notified_gates = advanced.notified_gates
        if advanced.halt_reason:
            self._state.persist("orchestrator: halt")
            return advanced.halt_reason

        # SPAWN
        plans = plan_spawns(
            state=self._state,
            workers=self._workers,
            executor=executor,
            runtime=self._runtime,
            max_workers=self._max_workers,
            max_task_rounds=self._max_task_rounds,
        )
        self._state.persist("orchestrator: cycle update")
        self._state.sync()
        self._probe.state_synced()
        self._execute_spawns(plans, cycle_num)
        self._emit_cycle_completed(cycle_num, cycle_start, plans, collected.reaped)
        return self._check_convergence()

    # -- Apply helpers -------------------------------------------------------

    def _apply_intake(self, result: IntakeResult) -> None:
        """Apply intake result: pin spec_refs, emit probe, reset failure flag."""
        if not result.ran:
            return
        if result.unprocessed_specs:
            self._probe.intake_specs_detected(
                specs=result.unprocessed_specs,
                cycle=self._current_cycle,
            )
        self._has_failures_since_intake = False
        if self._spec_source is not None:
            version = self._spec_source.current_version()
            world = self._state.get_world()
            # Pin new tasks
            if result.created_count > 0:
                for task in world.tasks.values():
                    if task.id not in result.tasks_before and "@" not in task.spec_ref:
                        self._state.set_spec_ref(task.id, f"{task.spec_ref}@{version}")
            # Re-pin pre-existing tasks whose specs were modified.
            # Only re-pin if the PM created new tasks for the spec (covering
            # the delta) OR the task is still in-progress (will see the new
            # spec when it runs). Complete/failed tasks with no new work keep
            # their old SHA so intake keeps re-triggering until the PM acts.
            new_task_specs = {
                t.spec_ref.split("@")[0]
                for t in world.tasks.values()
                if t.id not in result.tasks_before
            }
            for task in world.tasks.values():
                if task.id not in result.tasks_before:
                    continue
                spec_path = task.spec_ref.split("@")[0]
                if spec_path not in set(result.unprocessed_specs):
                    continue
                should_repin = task.status == TaskStatus.IN_PROGRESS or spec_path in new_task_specs
                if should_repin:
                    self._state.set_spec_ref(task.id, f"{spec_path}@{version}")
        self._probe.intake_ran(
            unprocessed_specs=result.unprocessed_count,
            created_tasks=result.created_count,
            success=result.success,
            cycle=self._current_cycle,
            duration_s=result.duration_s,
        )

    def _unprocessed_specs(self) -> list[str]:
        """Return spec file paths that have no corresponding task."""
        return [e.path for e in _detect_spec_entries(self._state, self._spec_source)]

    def _collect_cycle_findings(self, reaped_results: dict[str, WorkerResult]) -> str:
        """Collect findings from all failed results this cycle."""
        sections: list[str] = []
        for task_id, result in reaped_results.items():
            if result.verdict == Verdict.FAIL:
                sections.append(f"### {task_id}\n{result.detail}")
        return "\n\n".join(sections)

    def _execute_spawns(self, plans: list[SpawnPlan], cycle_num: int) -> None:
        """Execute spawn operations (side effects)."""
        if plans and self._current_cycle < self._spawn_skip_until:
            return
        for plan in plans:
            task = self._state.get_task(plan.task_id)
            branch = task.branch or f"{BRANCH_PREFIX}/{plan.task_id}"
            if task.branch is None:
                self._state.set_task_branch(plan.task_id, branch)
            if plan.transition_status is not None:
                self._state.transition_task(
                    plan.task_id,
                    plan.transition_status,
                    plan.transition_phase,
                )
            prompt = self._compose_prompt(task, plan.role, cycle=cycle_num)
            try:
                # Rebase existing branches onto trunk before spawning so workers
                # see the latest process-improver changes and state files.
                if task.branch is not None and self._pr is not None:
                    self._pr.rebase_branch(branch, self._base_branch)
                self._runtime.push_branch(branch)
                self._probe.branch_pushed(branch=branch)
                handle = self._runtime.spawn(plan.task_id, plan.role, prompt=prompt, branch=branch)
            except Exception:
                self._handle_spawn_failure(plan, task, branch, cycle_num)
                if self._spawn_skip_until > self._current_cycle:
                    break
                continue
            self._spawn_failures = 0
            self._spawn_task_failures.pop(plan.task_id, None)
            self._workers[plan.task_id] = (handle, plan.position, time.monotonic())
            self._probe.worker_spawned(
                task_id=plan.task_id,
                role=plan.role,
                branch=branch,
                round=task.round,
                cycle=cycle_num,
                spec_ref=task.spec_ref,
            )

    def _handle_spawn_failure(
        self, plan: SpawnPlan, task: Task, branch: str, cycle_num: int
    ) -> None:
        """Track spawn failure, apply backoff and task failure if needed."""
        self._spawn_failures += 1
        task_fails = self._spawn_task_failures.get(plan.task_id, 0) + 1
        self._spawn_task_failures[plan.task_id] = task_fails
        cooldown_cycles = 0
        if self._spawn_failures >= 3:
            cooldown_cycles = min(2 ** (self._spawn_failures - 2), 32)
            self._spawn_skip_until = self._current_cycle + cooldown_cycles
        self._probe.spawn_failed(
            task_id=plan.task_id,
            role=plan.role,
            branch=branch,
            attempt=task_fails,
            max_attempts=3,
            cooldown_cycles=cooldown_cycles,
            cycle=cycle_num,
        )
        if task_fails >= 3:
            reason = f"spawn failed 3 times for {plan.role} on branch {branch}"
            self._state.transition_task(plan.task_id, TaskStatus.FAILED, phase=None)
            self._probe.task_failed(
                task_id=plan.task_id,
                spec_ref=task.spec_ref,
                reason=reason,
                round=task.round,
                cycle=cycle_num,
            )
            self._spawn_task_failures.pop(plan.task_id, None)

    def _compose_prompt(self, task: Task, role: str, cycle: int) -> str:
        """Compose a prompt for a worker."""
        if self._composer is None:
            return ""
        findings = self._state.get_findings(task.id)
        pr_feedback = ""
        if task.pr and self._pr is not None:
            pr_feedback = self._pr.get_feedback(task.pr)
        context = TaskContext(
            task_id=task.id,
            spec_ref=task.spec_ref,
            findings=findings,
            round=task.round,
            pr_feedback=pr_feedback,
        )
        composed = self._composer.compose(
            role=role,
            context=context,
            epilogue=self._runtime.worker_epilogue(),
        )
        self._probe.prompt_composed(
            task_id=task.id,
            role=role,
            prompt_text=composed.text,
            sections=composed.sections,
            round=task.round,
            cycle=cycle,
        )
        return composed.text

    def _delete_remote_branch(self, branch: str) -> None:
        """Best-effort delete of a remote branch. Failures are swallowed."""
        import contextlib
        import subprocess

        with contextlib.suppress(Exception):
            subprocess.run(
                ["git", "push", "origin", "--delete", branch],
                capture_output=True,
                text=True,
            )

    def _check_convergence(self) -> str | None:
        """Check if all tasks are complete/failed."""
        all_tasks = self._state.get_world().tasks
        if not all_tasks:
            return None
        all_done = all(
            t.status in (TaskStatus.COMPLETE, TaskStatus.FAILED) for t in all_tasks.values()
        )
        if all_done and not self._workers:
            if all(t.status == TaskStatus.COMPLETE for t in all_tasks.values()):
                return "all tasks complete"
            return "all tasks resolved (some failed)"
        return None

    def _emit_halted(self, reason: str, total_cycles: int) -> None:
        world = self._state.get_world()
        self._probe.orchestrator_halted(
            reason=reason,
            total_cycles=total_cycles,
            completed_tasks=sum(1 for t in world.tasks.values() if t.status == TaskStatus.COMPLETE),
            failed_tasks=sum(1 for t in world.tasks.values() if t.status == TaskStatus.FAILED),
        )

    def _emit_cycle_completed(
        self,
        cycle_num: int,
        cycle_start: float,
        plans: list[SpawnPlan],
        reaped_results: dict[str, WorkerResult],
    ) -> None:
        all_tasks = self._state.get_world().tasks
        self._probe.cycle_completed(
            cycle=cycle_num,
            active_workers=len(self._workers),
            not_started=sum(1 for t in all_tasks.values() if t.status == TaskStatus.NOT_STARTED),
            in_progress=sum(1 for t in all_tasks.values() if t.status == TaskStatus.IN_PROGRESS),
            complete=sum(1 for t in all_tasks.values() if t.status == TaskStatus.COMPLETE),
            failed=sum(1 for t in all_tasks.values() if t.status == TaskStatus.FAILED),
            spawned_ids=tuple(p.task_id for p in plans),
            reaped_ids=tuple(reaped_results.keys()),
            duration_s=time.monotonic() - cycle_start,
        )
