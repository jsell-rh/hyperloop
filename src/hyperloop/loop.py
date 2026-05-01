"""Orchestrator loop -- thin coordinator that delegates to cycle phases.

Runs a 4-phase cycle: COLLECT, RECONCILE, ADVANCE, SPAWN.
Each phase returns a result dataclass; the Orchestrator applies mutations.
"""

from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, cast

from hyperloop.adapters.probe import NullProbe
from hyperloop.cycle import (
    BRANCH_PREFIX,
    advance,
    collect,
    extract_roles_from_phases,
    plan_spawns,
    run_intake,
)
from hyperloop.cycle.helpers import build_world
from hyperloop.cycle.intake import _detect_spec_entries
from hyperloop.domain.deps import detect_cycles
from hyperloop.domain.model import (
    Phase,
    PMFailureResponse,
    Task,
    TaskContext,
    TaskStatus,
    Verdict,
    WorkerHandle,
    WorkerResult,
)
from hyperloop.domain.reconciler import (
    Summary,
    check_convergence_needed,
    detect_coverage_gaps,
    detect_freshness_drift,
    detect_phase_orphans,
    handle_deleted_specs,
    handle_pm_failure,
    plan_gc,
)

if TYPE_CHECKING:
    from hyperloop.compose import PromptComposer
    from hyperloop.cycle.intake import IntakeResult
    from hyperloop.cycle.spawn import SpawnPlan
    from hyperloop.domain.model import Process
    from hyperloop.ports.channel import ChannelPort
    from hyperloop.ports.hook import CycleHook
    from hyperloop.ports.pr import PRPort
    from hyperloop.ports.probe import OrchestratorProbe
    from hyperloop.ports.runtime import Runtime
    from hyperloop.ports.signal import SignalPort
    from hyperloop.ports.spec_source import SpecSource
    from hyperloop.ports.state import StateStore
    from hyperloop.ports.step_executor import StepExecutor


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
        step_executor: StepExecutor | None = None,
        signal_port: SignalPort | None = None,
        channel: ChannelPort | None = None,
        pr: PRPort | None = None,
        spec_source: SpecSource | None = None,
        hooks: list[CycleHook] | None = None,
        composer: PromptComposer | None = None,
        poll_interval: float = 30.0,
        probe: OrchestratorProbe | None = None,
        gc_retention_days: int = 30,
        gc_run_every_cycles: int = 10,
        pm_max_failures: int = 5,
        max_auditors: int = 3,
    ) -> None:
        self._state = state
        self._runtime = runtime
        self._process = process
        self._max_workers = max_workers
        self._max_task_rounds = max_task_rounds
        self._max_action_attempts = max_action_attempts
        self._base_branch = base_branch
        self._step_executor = step_executor
        self._signal_port = signal_port
        self._channel = channel
        self._pr = pr
        self._spec_source = spec_source
        self._hooks: list[CycleHook] = hooks if hooks is not None else []
        self._composer = composer
        self._poll_interval = poll_interval
        self._probe: OrchestratorProbe = probe or NullProbe()
        self._gc_retention_days = gc_retention_days
        self._gc_run_every_cycles = gc_run_every_cycles
        self._pm_max_failures = pm_max_failures
        self._max_auditors = max_auditors

        self._workers: dict[str, tuple[WorkerHandle, float]] = {}
        self._current_cycle: int = 0
        self._spawn_failures: int = 0
        self._spawn_skip_until: int = 0
        self._spawn_task_failures: dict[str, int] = {}
        self._has_failures_since_intake: bool = False
        self._last_audits_run: int = 0

        # Reconciler state
        self._converged_specs: set[str] = set()
        self._converged_loaded: bool = False
        self._pm_consecutive_failures: int = 0
        self._pm_skip_until: int = 0
        self._gc_last_cycle: int = 0
        self._task_ages: dict[str, float] = {}
        self._has_drift: bool = False

    def validate_templates(self) -> None:
        """Validate that every role in the phase map has a resolved template."""
        if self._composer is None:
            return
        roles = extract_roles_from_phases(self._process.phases)
        missing = [r for r in roles if r not in self._composer._templates]
        if missing:
            msg = (
                f"Phase map references roles with no agent template: {sorted(missing)}. "
                "Check that base/ has definitions for these roles and "
                "kustomize build resolves them."
            )
            raise ValueError(msg)

    def run_loop(self, max_cycles: int = 200) -> str:
        """Run the orchestrator loop until halt or max_cycles."""
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

    def run_cycle(self, cycle_num: int = 0) -> str | None:
        """Run one cycle. Returns halt reason or None."""
        self._current_cycle = cycle_num
        cycle_start = time.monotonic()

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
                    probe=self._probe,
                    cycle=cycle_num,
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
            completed=sum(1 for t in world.tasks.values() if t.status == TaskStatus.COMPLETED),
            failed=sum(1 for t in world.tasks.values() if t.status == TaskStatus.FAILED),
        )

        # COLLECT
        self._probe.collect_started(cycle=cycle_num)
        collect_start = time.monotonic()
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

        # Emit crash notifications for workers whose poll status was FAILED
        for task_id in collected.crashed_task_ids:
            worker_info = collected.reaped_metadata.get(task_id)
            if worker_info is not None:
                handle, _ = worker_info
                task = self._state.get_task(task_id)
                self._probe.worker_crash_detected(
                    task_id=task_id,
                    role=handle.role,
                    branch=task.branch or "",
                )
                if self._channel is not None:
                    self._channel.worker_crashed(
                        task=task,
                        role=handle.role,
                        branch=task.branch or "",
                    )

        if collected.reaped:
            for hook in self._hooks:
                hook.after_reap(results=collected.reaped, cycle=cycle_num)
        self._probe.collect_completed(
            cycle=cycle_num,
            duration_s=time.monotonic() - collect_start,
            reaped_count=len(collected.reaped),
        )

        # RECONCILE
        halt_reason = self._run_reconcile(cycle_num)
        if halt_reason is not None:
            self._state.persist("orchestrator: halt")
            return halt_reason

        # ADVANCE
        self._probe.advance_started(cycle=cycle_num)
        advance_start = time.monotonic()
        advanced = advance(
            state=self._state,
            reaped=collected.reaped,
            reaped_metadata=collected.reaped_metadata,
            phases=self._process.phases,
            step_executor=self._step_executor,
            signal_port=self._signal_port,
            channel=self._channel,
            pr=self._pr,
            probe=self._probe,
            max_task_rounds=self._max_task_rounds,
            cycle=cycle_num,
            running_tasks=frozenset(self._workers.keys()),
        )
        for t in advanced.transitions:
            if t.reset_branch:
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
            if t.status == TaskStatus.COMPLETED:
                completed_task = self._state.get_task(t.task_id)
                self._write_summary(completed_task)
        self._probe.advance_completed(
            cycle=cycle_num,
            duration_s=time.monotonic() - advance_start,
            transitions=len(advanced.transitions),
        )
        if advanced.halt_reason:
            self._state.persist("orchestrator: halt")
            return advanced.halt_reason

        # SPAWN
        self._probe.spawn_started(cycle=cycle_num)
        spawn_start = time.monotonic()
        spawn_result = plan_spawns(
            state=self._state,
            workers=self._workers,
            phases=self._process.phases,
            runtime=self._runtime,
            max_workers=self._max_workers,
            max_task_rounds=self._max_task_rounds,
        )
        self._state.persist("orchestrator: cycle update")
        sync_error = self._state.sync()
        if sync_error is not None:
            self._probe.state_sync_failed(error=sync_error)
        else:
            self._probe.state_synced()
        self._execute_spawns(spawn_result.plans, cycle_num)
        self._probe.spawn_completed(
            cycle=cycle_num,
            duration_s=time.monotonic() - spawn_start,
            spawned_count=len(spawn_result.plans),
        )
        self._emit_cycle_completed(cycle_num, cycle_start, spawn_result.plans, collected.reaped)
        if spawn_result.halt_reason is not None:
            return spawn_result.halt_reason
        return self._check_convergence()

    # -- Reconcile phase -----------------------------------------------------

    def _run_reconcile(self, cycle_num: int) -> str | None:
        """Run reconciler checks: drift, deleted specs, orphans, convergence, intake, GC.

        Returns halt reason if PM failure threshold is reached, else None.
        """
        reconcile_start = time.monotonic()
        self._probe.reconcile_started(cycle=cycle_num)

        world = self._state.get_world()

        # 1. Handle deleted specs -- retire tasks referencing missing specs
        self._handle_deleted_specs(world.tasks, cycle_num)

        # 2. Detect phase orphans -- reset tasks at phases not in current map
        self._handle_phase_orphans(world.tasks, cycle_num)

        # 3. Drift detection (coverage + freshness)
        drift_count = self._run_drift_detection(world.tasks, cycle_num)

        # 4. Convergence tracking (auditor for completed specs)
        if not self._converged_loaded:
            self._load_converged_specs()
            self._converged_loaded = True
        self._last_audits_run = 0
        self._run_convergence_check(world.tasks, cycle_num)

        # audits_run is returned by the convergence check
        audits_run = self._last_audits_run

        # 5. Run intake (PM agent for task creation) -- skip during backoff
        if self._current_cycle < self._pm_skip_until:
            intake_result = run_intake(
                self._state,
                self._runtime,
                None,  # skip intake by passing no composer
                False,
            )
        else:
            intake_result = run_intake(
                self._state,
                self._runtime,
                self._composer,
                self._has_failures_since_intake or self._has_drift,
                spec_source=self._spec_source,
            )
        self._apply_intake(intake_result)

        # 6. Track PM failures and apply backoff
        halt_reason: str | None = None
        if intake_result.ran and not intake_result.success:
            self._pm_consecutive_failures += 1
            response = handle_pm_failure(self._pm_consecutive_failures, self._pm_max_failures)
            if response == PMFailureResponse.HALT:
                halt_reason = (
                    f"PM agent unreachable after {self._pm_consecutive_failures} "
                    f"consecutive failures"
                )
        elif intake_result.ran and intake_result.success:
            self._pm_consecutive_failures = 0
            self._pm_skip_until = 0

        if halt_reason is None and intake_result.ran and not intake_result.success:
            # Apply exponential backoff (non-halt case)
            backoff_cycles = min(2**self._pm_consecutive_failures, 32)
            self._pm_skip_until = self._current_cycle + backoff_cycles

        # 7. Garbage collection
        gc_pruned = self._run_gc(cycle_num)

        # Reset drift flag after intake has had a chance to process it
        self._has_drift = False

        self._probe.reconcile_completed(
            cycle=cycle_num,
            duration_s=time.monotonic() - reconcile_start,
            drift_count=drift_count,
            audits_run=audits_run,
            gc_pruned=gc_pruned,
        )

        return halt_reason

    def _run_drift_detection(self, tasks: dict[str, Task], cycle_num: int) -> int:
        """Run coverage and freshness drift detection.

        Returns the number of drifts detected.
        """
        if self._spec_source is None:
            return 0

        spec_files = self._state.list_files("specs/**/*.spec.md")
        spec_files_alt = self._state.list_files("specs/**/*.md")
        current_specs = sorted(set(spec_files) | set(spec_files_alt))

        if not current_specs:
            return 0

        # Load summaries from state
        summaries = self._load_summaries()

        drift_count = 0

        # Coverage gaps
        coverage_gaps = detect_coverage_gaps(tasks, current_specs, summaries)
        for gap in coverage_gaps:
            self._probe.drift_detected(
                spec_path=gap.spec_path,
                drift_type=gap.drift_type,
                detail=gap.detail,
                cycle=cycle_num,
            )
            self._has_drift = True
            drift_count += 1

        # Freshness drift -- per-file blob SHA, not repo HEAD
        spec_versions: dict[str, str] = {}
        for spec_path in current_specs:
            v = self._spec_source.file_version(spec_path)
            if v:
                spec_versions[spec_path] = v

        # Normalize pinned SHAs: tasks pinned before the blob-SHA fix may have
        # commit SHAs. Resolve them to blob SHAs so the comparison is apples-to-apples.
        normalized_tasks = dict(tasks)
        for task in normalized_tasks.values():
            if "@" in task.spec_ref:
                spec_path = task.spec_ref.split("@")[0]
                pinned = task.spec_ref.split("@")[1]
                blob = self._spec_source.file_version_at(spec_path, pinned)
                if blob != pinned:
                    normalized_tasks[task.id] = Task(
                        id=task.id,
                        title=task.title,
                        spec_ref=f"{spec_path}@{blob}",
                        status=task.status,
                        phase=task.phase,
                        deps=task.deps,
                        round=task.round,
                        branch=task.branch,
                        pr=task.pr,
                    )

        freshness_drifts = detect_freshness_drift(normalized_tasks, spec_versions, summaries)
        for drift in freshness_drifts:
            self._probe.drift_detected(
                spec_path=drift.spec_path,
                drift_type=drift.drift_type,
                detail=drift.detail,
                cycle=cycle_num,
            )
            self._has_drift = True
            drift_count += 1

        return drift_count

    def _run_convergence_check(self, tasks: dict[str, Task], cycle_num: int) -> None:
        """Check for specs needing alignment audit and run auditors concurrently."""
        if self._composer is None:
            return

        if "auditor" not in self._composer._templates:
            return

        needs_audit = check_convergence_needed(tasks, self._converged_specs)
        if not needs_audit:
            return

        self._probe.auditors_started(count=len(needs_audit), cycle=cycle_num)
        audits_run = 0

        def _run_one(spec_ref: str) -> tuple[str, WorkerResult]:
            self._probe.audit_started(spec_ref=spec_ref, cycle=cycle_num)
            prompt = self._compose_auditor_prompt(spec_ref)
            result = self._runtime.run_auditor(spec_ref, prompt)
            return spec_ref, result

        start_times: dict[str, float] = {}
        with ThreadPoolExecutor(max_workers=self._max_auditors) as executor:
            futures: dict[Future[tuple[str, WorkerResult]], str] = {}
            for spec_ref in needs_audit:
                start_times[spec_ref] = time.monotonic()
                futures[executor.submit(_run_one, spec_ref)] = spec_ref

            for future in as_completed(futures):
                spec_ref = futures[future]
                try:
                    _, result = future.result()
                except Exception:
                    result = WorkerResult(
                        verdict=Verdict.FAIL,
                        detail=f"Auditor raised exception for {spec_ref}",
                    )
                duration_s = time.monotonic() - start_times[spec_ref]
                spec_path = spec_ref.split("@")[0] if "@" in spec_ref else spec_ref
                audits_run += 1

                if result.verdict == Verdict.PASS:
                    self._converged_specs.add(spec_ref)
                    self._store_converged(spec_ref)
                    self._probe.convergence_marked(
                        spec_path=spec_path, spec_ref=spec_ref, cycle=cycle_num
                    )
                    self._probe.audit_ran(
                        spec_ref=spec_ref,
                        result="aligned",
                        cycle=cycle_num,
                        duration_s=duration_s,
                    )
                else:
                    self._probe.audit_ran(
                        spec_ref=spec_ref,
                        result="misaligned",
                        cycle=cycle_num,
                        duration_s=duration_s,
                    )
                    # Store audit finding with the agent's actual detail
                    self._state.store_review(
                        task_id=f"audit-{spec_ref}",
                        round=0,
                        role="auditor",
                        verdict="fail",
                        detail=result.detail,
                    )
                    self._has_drift = True

        self._last_audits_run = audits_run

    def _compose_auditor_prompt(self, spec_ref: str) -> str:
        """Compose the auditor prompt for a spec_ref."""
        if self._composer is None:
            return ""
        context = TaskContext(
            task_id="auditor",
            spec_ref=spec_ref,
            findings="",
            round=0,
        )
        composed = self._composer.compose(
            role="auditor",
            context=context,
            epilogue=self._runtime.worker_epilogue(),
        )
        self._probe.prompt_composed(
            task_id=f"auditor-{spec_ref}",
            role="auditor",
            prompt_text=composed.text,
            sections=composed.sections,
            round=0,
            cycle=self._current_cycle,
        )
        return composed.text

    def _handle_deleted_specs(self, tasks: dict[str, Task], cycle_num: int) -> None:
        """Detect tasks referencing deleted specs and fail them."""
        # Gather current spec paths from the state store
        spec_files = self._state.list_files("specs/**/*.spec.md")
        # Also include specs matching "specs/*.md" for backward compat
        spec_files_alt = self._state.list_files("specs/**/*.md")
        current_spec_paths: set[str] = set(spec_files) | set(spec_files_alt)

        # Only check for deleted specs when the store tracks spec files.
        # If no spec files exist at all, skip -- the store may not track them.
        if not current_spec_paths:
            return

        retirements = handle_deleted_specs(tasks, current_spec_paths)
        for retirement in retirements:
            self._state.transition_task(retirement.task_id, TaskStatus.FAILED, phase=None)
            task = self._state.get_task(retirement.task_id)
            self._probe.task_failed(
                task_id=retirement.task_id,
                spec_ref=task.spec_ref,
                reason=retirement.reason,
                round=task.round,
                cycle=cycle_num,
            )

    def _handle_phase_orphans(self, tasks: dict[str, Task], cycle_num: int) -> None:
        """Detect tasks at phases not in the current phase map and reset them."""
        orphans = detect_phase_orphans(tasks, self._process.phases)
        first_phase_key = next(iter(self._process.phases), None) if self._process.phases else None
        for orphan in orphans:
            task = self._state.get_task(orphan.task_id)
            if first_phase_key is not None:
                self._state.transition_task(
                    orphan.task_id,
                    TaskStatus.IN_PROGRESS,
                    phase=Phase(first_phase_key),
                    round=task.round + 1,
                )
            else:
                self._state.reset_task(orphan.task_id)
            self._probe.task_reset(
                task_id=orphan.task_id,
                spec_ref=task.spec_ref,
                reason="process changed, PM migration failed",
                prior_round=task.round,
                cycle=cycle_num,
            )

    def _run_gc(self, cycle_num: int) -> int:
        """Run garbage collection if on the configured interval.

        Returns the number of tasks pruned.
        """
        if self._gc_run_every_cycles <= 0:
            return 0
        if cycle_num % self._gc_run_every_cycles != 0:
            return 0

        world = self._state.get_world()
        gc_actions = plan_gc(
            tasks=world.tasks,
            retention_days=self._gc_retention_days,
            task_ages=self._task_ages,
        )
        for action in gc_actions:
            task = world.tasks[action.task_id]
            self._write_summary(task)
            self._state.delete_task(action.task_id)
        if gc_actions:
            self._probe.gc_ran(
                pruned_count=len(gc_actions),
                cycle=cycle_num,
            )
        self._gc_last_cycle = cycle_num
        return len(gc_actions)

    def _load_summaries(self) -> dict[str, Summary]:
        """Load all summaries from the state store and parse into Summary objects."""
        import yaml

        raw_summaries = self._state.list_summaries()
        summaries: dict[str, Summary] = {}
        for spec_path, content in raw_summaries.items():
            parsed = yaml.safe_load(content)
            if not isinstance(parsed, dict):
                continue
            d = cast("dict[str, object]", parsed)
            raw_themes = d.get("failure_themes", [])
            themes = (
                [str(t) for t in cast("list[object]", raw_themes)]
                if isinstance(raw_themes, list)
                else []
            )
            summaries[spec_path] = Summary(
                spec_path=str(d.get("spec_path", spec_path)),
                spec_ref=str(d.get("spec_ref", spec_path)),
                total_tasks=int(str(d.get("total_tasks", 0))),
                completed=int(str(d.get("completed", 0))),
                failed=int(str(d.get("failed", 0))),
                failure_themes=themes,
                last_audit=str(d["last_audit"]) if d.get("last_audit") is not None else None,
                last_audit_result=str(d["last_audit_result"])
                if d.get("last_audit_result") is not None
                else None,
            )
        return summaries

    def _load_converged_specs(self) -> None:
        """Load persisted convergence records and populate _converged_specs.

        For each stored record, compare the stored spec SHA against the
        current blob SHA. Only add to _converged_specs when they match.
        """
        import yaml

        raw = self._state.list_converged()
        for spec_path, content in raw.items():
            parsed = yaml.safe_load(content)
            if not isinstance(parsed, dict):
                continue
            d = cast("dict[str, object]", parsed)
            spec_ref = str(d.get("spec_ref", ""))
            if "@" not in spec_ref:
                continue
            stored_sha = spec_ref.split("@")[1]

            if self._spec_source is not None:
                current_sha = self._spec_source.file_version(spec_path)
                if current_sha and current_sha != stored_sha:
                    continue

            self._converged_specs.add(spec_ref)

    def _store_converged(self, spec_ref: str) -> None:
        """Persist a convergence record to the state branch.

        Normalizes the spec_ref SHA to a blob SHA so that
        _load_converged_specs can compare against file_version().
        """
        from datetime import UTC, datetime

        import yaml

        spec_path = spec_ref.split("@")[0] if "@" in spec_ref else spec_ref
        # Normalize to blob SHA for consistent comparison with file_version()
        stored_ref = spec_ref
        if "@" in spec_ref and self._spec_source is not None:
            pinned = spec_ref.split("@")[1]
            blob = self._spec_source.file_version_at(spec_path, pinned)
            if blob and blob != pinned:
                stored_ref = f"{spec_path}@{blob}"
        data = yaml.dump(
            {
                "spec_ref": stored_ref,
                "audited_at": datetime.now(UTC).isoformat(),
            },
            default_flow_style=False,
            sort_keys=False,
        )
        self._state.store_converged(spec_path, data)

    def _write_summary(self, task: Task) -> None:
        """Build and store a Summary record for a task (on completion or GC prune)."""
        import yaml

        spec_path = task.spec_ref.split("@")[0]

        summary = Summary(
            spec_path=spec_path,
            spec_ref=task.spec_ref,
            total_tasks=1,
            completed=1 if task.status == TaskStatus.COMPLETED else 0,
            failed=1 if task.status == TaskStatus.FAILED else 0,
            failure_themes=[],
            last_audit=None,
            last_audit_result=None,
        )

        summary_yaml = yaml.dump(
            {
                "spec_path": summary.spec_path,
                "spec_ref": summary.spec_ref,
                "total_tasks": summary.total_tasks,
                "completed": summary.completed,
                "failed": summary.failed,
                "failure_themes": summary.failure_themes,
                "last_audit": summary.last_audit,
                "last_audit_result": summary.last_audit_result,
            },
            default_flow_style=False,
            sort_keys=False,
        )
        self._state.store_summary(spec_path, summary_yaml)

    # -- Apply helpers -------------------------------------------------------

    def _apply_intake(self, result: IntakeResult) -> None:
        """Apply intake result: pin spec_refs, emit probe, reset failure flag."""
        if not result.ran:
            return
        self._has_failures_since_intake = False
        if self._spec_source is not None:
            world = self._state.get_world()
            # Pin new tasks using per-file blob SHA
            if result.created_count > 0:
                for task in world.tasks.values():
                    if task.id not in result.tasks_before and "@" not in task.spec_ref:
                        v = self._spec_source.file_version(task.spec_ref)
                        if v:
                            self._state.set_spec_ref(task.id, f"{task.spec_ref}@{v}")
            # Re-pin pre-existing tasks whose specs were modified
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
                    v = self._spec_source.file_version(spec_path)
                    if v:
                        self._state.set_spec_ref(task.id, f"{spec_path}@{v}")
        # Create summaries for specs the PM evaluated but created no tasks for.
        # Without this, detect_coverage_gaps fires again next cycle and the PM
        # re-evaluates the same specs indefinitely.
        if result.success and self._spec_source is not None:
            import yaml

            world = self._state.get_world()
            new_task_specs = {
                t.spec_ref.split("@")[0]
                for t in world.tasks.values()
                if t.id not in result.tasks_before
            }
            for spec_path in result.unprocessed_specs:
                if spec_path not in new_task_specs:
                    v = self._spec_source.file_version(spec_path)
                    if v:
                        summary_yaml = yaml.dump(
                            {
                                "spec_path": spec_path,
                                "spec_ref": f"{spec_path}@{v}",
                                "total_tasks": 0,
                                "completed": 0,
                                "failed": 0,
                                "failure_themes": [],
                                "last_audit": None,
                                "last_audit_result": None,
                            },
                            default_flow_style=False,
                            sort_keys=False,
                        )
                        self._state.store_summary(spec_path, summary_yaml)

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
            # Pin spec_ref with blob SHA if not already pinned
            if "@" not in task.spec_ref and self._spec_source is not None:
                v = self._spec_source.file_version(task.spec_ref)
                if v:
                    self._state.set_spec_ref(task.id, f"{task.spec_ref}@{v}")
                    task = self._state.get_task(plan.task_id)
            prompt = self._compose_prompt(task, plan.role, cycle=cycle_num)
            try:
                # Re-fetch task after potential branch assignment to avoid
                # stale reference skipping rebase on first spawn.
                fresh_task = self._state.get_task(plan.task_id)
                if fresh_task.branch is not None and self._pr is not None:
                    rebase_result = self._pr.rebase_branch(branch, self._base_branch)
                    if not rebase_result.success and rebase_result.conflicting_files:
                        prompt += _format_rebase_conflicts(
                            rebase_result.conflicting_files,
                            self._base_branch,
                        )
                        self._probe.rebase_conflict_detected(
                            task_id=plan.task_id,
                            branch=branch,
                            conflicting_files=rebase_result.conflicting_files,
                            cycle=cycle_num,
                        )
                self._runtime.push_branch(branch)
                handle = self._runtime.spawn(plan.task_id, plan.role, prompt=prompt, branch=branch)
            except Exception:
                self._handle_spawn_failure(plan, task, branch, cycle_num)
                if self._spawn_skip_until > self._current_cycle:
                    break
                continue
            self._spawn_failures = 0
            self._spawn_task_failures.pop(plan.task_id, None)
            self._workers[plan.task_id] = (handle, time.monotonic())
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
            t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED) for t in all_tasks.values()
        )
        if all_done and not self._workers:
            if all(t.status == TaskStatus.COMPLETED for t in all_tasks.values()):
                return "all tasks complete"
            return "all tasks resolved (some failed)"
        return None

    def _emit_halted(self, reason: str, total_cycles: int) -> None:
        world = self._state.get_world()
        self._probe.orchestrator_halted(
            reason=reason,
            total_cycles=total_cycles,
            completed_tasks=sum(
                1 for t in world.tasks.values() if t.status == TaskStatus.COMPLETED
            ),
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
            completed=sum(1 for t in all_tasks.values() if t.status == TaskStatus.COMPLETED),
            failed=sum(1 for t in all_tasks.values() if t.status == TaskStatus.FAILED),
            spawned_ids=tuple(p.task_id for p in plans),
            reaped_ids=tuple(reaped_results.keys()),
            duration_s=time.monotonic() - cycle_start,
        )


def _format_rebase_conflicts(files: tuple[str, ...], base_branch: str) -> str:
    sanitized = [f.replace("`", "").replace("\n", "") for f in files]
    file_list = "\n".join(f"- `{f}`" for f in sanitized)
    return (
        f"\n## Rebase Conflicts\n\n"
        f"Your branch could not be automatically rebased onto {base_branch}.\n"
        f"Conflicting files:\n{file_list}\n\n"
        f"You MUST run `git rebase {base_branch}` and resolve these "
        f"conflicts before doing any other work. After resolving, run "
        f"tests to verify correctness."
    )
