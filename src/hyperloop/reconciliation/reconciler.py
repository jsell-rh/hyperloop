from __future__ import annotations

import time

from datetime import datetime, timezone

from hyperloop.reconciliation.models.cancellation_reason import CancellationReason
from hyperloop.reconciliation.models.cyclic_dependency_error import (
    CyclicDependencyError,
)
from hyperloop.reconciliation.models.event import Event, EventType
from hyperloop.reconciliation.models.event_reason import EventReason
from hyperloop.reconciliation.models.halt_reason import HaltReason
from hyperloop.reconciliation.models.merge_result import MergeOutcome
from hyperloop.reconciliation.models.plan import Plan
from hyperloop.reconciliation.models.poll_result import AgentStatus, AgentVerdict
from hyperloop.reconciliation.models.proposed_task import ProposedTask
from hyperloop.reconciliation.models.spec_diff import SpecDiff
from hyperloop.reconciliation.models.spec_entry import SpecEntry
from hyperloop.reconciliation.models.spec_plan import SpecPlan, SpecPlanStatus
from hyperloop.reconciliation.models.task import Task, TaskStatus
from hyperloop.reconciliation.models.task_briefing import TaskBriefing
from hyperloop.reconciliation.ports.agent_runtime import AgentRuntime
from hyperloop.reconciliation.ports.observer import ChangeType, Observer
from hyperloop.reconciliation.ports.plan_store import PlanStore
from hyperloop.reconciliation.ports.prompt_composer import PromptComposer
from hyperloop.reconciliation.ports.spec_source import SpecSource
from hyperloop.reconciliation.ports.workspace_manager import WorkspaceManager


class Reconciler:
    def __init__(
        self,
        *,
        spec_source: SpecSource,
        plan_store: PlanStore,
        observer: Observer,
        agent_runtime: AgentRuntime,
        workspace_manager: WorkspaceManager,
        prompt_composer: PromptComposer | None = None,
        max_concurrent_tasks: int = 5,
        convergence_bound: int = 3,
        max_integration_retries: int = 3,
        max_task_retries: int = 3,
        max_redecompositions: int = 1,
        cycle_interval_seconds: int = 30,
    ) -> None:
        self._spec_source = spec_source
        self._plan_store = plan_store
        self._observer = observer
        self._agent_runtime = agent_runtime
        self._workspace_manager = workspace_manager
        self._prompt_composer = prompt_composer
        self._max_concurrent_tasks = max_concurrent_tasks
        self._convergence_bound = convergence_bound
        self._max_integration_retries = max_integration_retries
        self._max_task_retries = max_task_retries
        self._max_redecompositions = max_redecompositions
        self._cycle_interval_seconds = cycle_interval_seconds
        self._cycle: int = 0
        self._running: bool = False

    def run(self) -> None:
        self._recover()
        self._running = True

        plan = self._plan_store.get_plan()
        spec_count = sum(1 for sp in plan.spec_plans if not sp.superseded)
        self._observer.reconciler_started(spec_count=spec_count, cycle=self._cycle)

        try:
            while self._running:
                self.run_cycle()
                if self._running:
                    time.sleep(self._cycle_interval_seconds)
        except KeyboardInterrupt:
            pass

        self._observer.reconciler_halted(
            reason=HaltReason.SHUTDOWN, total_cycles=self._cycle
        )

    def stop(self) -> None:
        self._running = False

    def _recover(self) -> None:
        plan = self._plan_store.get_plan()
        stale = self._agent_runtime.detect_stale()

        if not stale:
            return

        self._observer.crash_recovery_started(stale_agent_count=len(stale))

        handle_to_task: dict[str, tuple[int, str]] = {}
        for sp in plan.spec_plans:
            for task in sp.tasks:
                if task.agent_handle is not None:
                    handle_to_task[task.agent_handle.id] = (task.id, task.spec_path)

        for handle in stale:
            if handle.id in handle_to_task:
                task_id, spec_path = handle_to_task[handle.id]
                self._observer.stale_agent_detected(
                    task_id=task_id, spec_path=spec_path
                )
            try:
                self._agent_runtime.cancel(handle)
            except Exception:
                pass

        for sp in plan.spec_plans:
            if sp.superseded:
                continue
            for task in sp.tasks:
                if task.status == TaskStatus.IN_PROGRESS:
                    task.status = TaskStatus.BACKLOG
                    task.agent_handle = None
            if sp.verification_handle is not None:
                sp.verification_handle = None
                if sp.status == SpecPlanStatus.VERIFYING:
                    sp.status = SpecPlanStatus.RECONCILING

        self._plan_store.write_plan(plan)

    def run_cycle(self) -> None:
        self._cycle += 1
        start = time.monotonic()

        self._spec_source.sync()
        if self._prompt_composer is not None:
            self._prompt_composer.rebuild_if_changed()
        plan = self._plan_store.get_plan()
        entries = self._spec_source.list_specs()

        specs_out_of_sync = self._count_out_of_sync(plan)
        tasks_in_progress = self._count_in_progress(plan)
        self._observer.cycle_started(
            cycle=self._cycle,
            specs_out_of_sync=specs_out_of_sync,
            tasks_in_progress=tasks_in_progress,
        )

        self._detect_divergence(plan, entries)
        self._invalidate_unsatisfiable_dependencies(plan)
        self._decompose(plan)
        tasks_dispatched = self._dispatch_tasks(plan)
        tasks_completed, tasks_failed = self._collect_results(plan)
        self._handle_retry_exhaustion(plan)
        self._collect_verification_results(plan)
        self._launch_verification(plan)

        self._plan_store.write_plan(plan)
        self._observer.plan_synced(cycle=self._cycle)

        duration = time.monotonic() - start
        self._observer.cycle_completed(
            cycle=self._cycle,
            duration_s=duration,
            specs_out_of_sync=self._count_out_of_sync(plan),
            tasks_dispatched=tasks_dispatched,
            tasks_completed=tasks_completed,
            tasks_failed=tasks_failed,
        )

    def _decompose(self, plan: Plan) -> None:
        out_of_sync = [
            sp
            for sp in plan.spec_plans
            if not sp.superseded and sp.status == SpecPlanStatus.OUT_OF_SYNC
        ]
        if not out_of_sync:
            return

        start = time.monotonic()
        self._observer.decomposition_started(
            specs_count=len(out_of_sync), cycle=self._cycle
        )

        spec_diffs: list[SpecDiff] = []
        for sp in out_of_sync:
            old_sha = self._find_last_synced_sha(plan, sp.path)
            spec_diffs.append(
                SpecDiff(
                    spec_path=sp.path,
                    blob_sha=sp.blob_sha,
                    old_blob_sha=old_sha,
                )
            )

        existing_tasks = self._collect_all_tasks(plan)
        events = self._collect_spec_events(out_of_sync)

        try:
            proposed = self._agent_runtime.launch_decomposition(
                spec_diffs, existing_tasks, events
            )
        except Exception as exc:
            self._handle_decomposition_failure(out_of_sync, str(exc))
            return

        try:
            tasks_created = self._materialize_tasks(plan, out_of_sync, proposed)
        except CyclicDependencyError as exc:
            self._handle_decomposition_failure(out_of_sync, str(exc))
            return

        duration = time.monotonic() - start
        self._observer.decomposition_completed(
            specs_count=len(out_of_sync),
            tasks_created=tasks_created,
            cycle=self._cycle,
            duration_s=duration,
        )
        for sp in out_of_sync:
            sp.record_event(
                reason=EventReason.DECOMPOSITION_COMPLETED,
                message=f"{tasks_created} tasks created",
                event_type=EventType.NORMAL,
                timestamp=datetime.now(timezone.utc),
            )

    def _handle_decomposition_failure(self, specs: list[SpecPlan], reason: str) -> None:
        self._observer.decomposition_failed(reason=reason, cycle=self._cycle)
        for sp in specs:
            sp.record_event(
                reason=EventReason.DECOMPOSITION_FAILED,
                message=reason,
                event_type=EventType.WARNING,
                timestamp=datetime.now(timezone.utc),
            )
            sp.reconciliation_attempts += 1
            if sp.reconciliation_attempts >= self._convergence_bound:
                sp.status = SpecPlanStatus.FAILED
                self._observer.spec_failed(
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    reason=f"Convergence bound ({self._convergence_bound}) exceeded",
                    cycle=self._cycle,
                )

    def _find_last_synced_sha(self, plan: Plan, path: str) -> str | None:
        for sp in reversed(plan.spec_plans):
            if sp.path == path and sp.status == SpecPlanStatus.SYNCED:
                return sp.blob_sha
        return None

    def _collect_all_tasks(self, plan: Plan) -> list[Task]:
        tasks: list[Task] = []
        for sp in plan.spec_plans:
            if sp.superseded:
                continue
            tasks.extend(sp.tasks)
        return tasks

    def _collect_spec_events(self, spec_plans: list[SpecPlan]) -> list[Event]:
        events: list[Event] = []
        for sp in spec_plans:
            events.extend(sp.events)
            for task in sp.tasks:
                events.extend(task.events)
        return events

    def _materialize_tasks(
        self,
        plan: Plan,
        out_of_sync: list[SpecPlan],
        proposed: list[ProposedTask],
    ) -> int:
        name_to_id: dict[str, int] = {}
        for sp in plan.spec_plans:
            if sp.superseded:
                continue
            for task in sp.tasks:
                name_to_id[task.name] = task.id

        tasks_with_proposed: list[tuple[Task, ProposedTask]] = []
        for pt in proposed:
            task_id = plan.next_task_id()
            name_to_id[pt.name] = task_id
            task = Task(
                id=task_id,
                spec_path=pt.spec_path,
                spec_blob_sha=pt.spec_blob_sha,
                name=pt.name,
                description=pt.description,
            )
            tasks_with_proposed.append((task, pt))

        for task, pt in tasks_with_proposed:
            task.depends_on = [
                name_to_id[dep_name]
                for dep_name in pt.depends_on
                if dep_name in name_to_id
            ]

        new_task_ids = {task.id for task, _ in tasks_with_proposed}
        self._validate_no_cycles(tasks_with_proposed, new_task_ids)

        tasks_by_key: dict[tuple[str, str], list[Task]] = {}
        for task, _ in tasks_with_proposed:
            key = (task.spec_path, task.spec_blob_sha)
            tasks_by_key.setdefault(key, []).append(task)

        for sp in out_of_sync:
            key = (sp.path, sp.blob_sha)
            tasks = tasks_by_key.get(key, [])
            plan.add_tasks(sp, tasks)
            for task in tasks:
                self._observer.task_created(
                    task_id=task.id,
                    spec_path=task.spec_path,
                    spec_blob_sha=task.spec_blob_sha,
                    name=task.name,
                    depends_on=task.depends_on,
                )

        return len(tasks_with_proposed)

    @staticmethod
    def _validate_no_cycles(
        tasks_with_proposed: list[tuple[Task, ProposedTask]],
        new_task_ids: set[int],
    ) -> None:
        adjacency: dict[int, list[int]] = {}
        id_to_name: dict[int, str] = {}
        for task, _ in tasks_with_proposed:
            id_to_name[task.id] = task.name
            adjacency[task.id] = [dep for dep in task.depends_on if dep in new_task_ids]

        visited: set[int] = set()
        in_stack: set[int] = set()

        for start in adjacency:
            if start in visited:
                continue
            stack: list[tuple[int, int]] = [(start, 0)]
            path: list[int] = []
            while stack:
                node, idx = stack[-1]
                if node not in in_stack:
                    in_stack.add(node)
                    path.append(node)
                neighbors = adjacency[node]
                if idx < len(neighbors):
                    stack[-1] = (node, idx + 1)
                    neighbor = neighbors[idx]
                    if neighbor in in_stack:
                        cycle_start = path.index(neighbor)
                        cycle = path[cycle_start:] + [neighbor]
                        raise CyclicDependencyError([id_to_name[cid] for cid in cycle])
                    if neighbor not in visited:
                        stack.append((neighbor, 0))
                else:
                    stack.pop()
                    in_stack.discard(node)
                    path.pop()
                    visited.add(node)

    def _dispatch_tasks(self, plan: Plan) -> int:
        in_progress_count = self._count_in_progress(plan)
        available_slots = self._max_concurrent_tasks - in_progress_count
        if available_slots <= 0:
            return 0

        unblocked = plan.get_unblocked_tasks()
        to_dispatch = unblocked[:available_slots]
        if not to_dispatch:
            return 0

        dispatched = 0
        for task in to_dispatch:
            sp = self._find_spec_plan_for_task(plan, task)
            if sp is not None and sp.delivery_workspace_id is None:
                sp.delivery_workspace_id = (
                    self._workspace_manager.create_delivery_workspace(
                        task.spec_blob_sha
                    )
                )

            spec_content = self._spec_source.read_at(task.spec_path, task.spec_blob_sha)
            workspace_briefing = self._format_workspace_briefing(task)
            workspace_id = self._workspace_manager.create_task_workspace(
                task.spec_blob_sha, task.id, workspace_briefing
            )
            task.workspace_id = workspace_id
            briefing = TaskBriefing(
                spec_content=spec_content,
                spec_path=task.spec_path,
                spec_blob_sha=task.spec_blob_sha,
                task_description=task.description,
                events=list(task.events),
                workspace_id=workspace_id,
            )
            try:
                handle = self._agent_runtime.launch_task(briefing)
            except Exception as exc:
                self._observer.agent_launch_failed(
                    task_id=task.id,
                    role="task",
                    reason=str(exc),
                    cycle=self._cycle,
                )
                continue
            task.status = TaskStatus.IN_PROGRESS
            task.agent_handle = handle
            self._observer.task_dispatched(
                task_id=task.id,
                spec_path=task.spec_path,
                spec_blob_sha=task.spec_blob_sha,
                retry_count=task.retry_count,
                cycle=self._cycle,
            )
            task.record_event(
                reason=EventReason.TASK_DISPATCHED,
                message=f"Dispatched (attempt {task.retry_count + 1})",
                event_type=EventType.NORMAL,
                timestamp=datetime.now(timezone.utc),
            )
            dispatched += 1

        return dispatched

    def _find_spec_plan_for_task(self, plan: Plan, task: Task) -> SpecPlan | None:
        for sp in plan.spec_plans:
            if sp.superseded:
                continue
            if sp.path == task.spec_path and sp.blob_sha == task.spec_blob_sha:
                return sp
        return None

    def _collect_results(self, plan: Plan) -> tuple[int, int]:
        completed = 0
        failed = 0
        for sp in plan.spec_plans:
            if sp.superseded:
                continue
            for task in sp.tasks:
                if task.status != TaskStatus.IN_PROGRESS or task.agent_handle is None:
                    continue
                try:
                    result = self._agent_runtime.poll(task.agent_handle)
                except Exception:
                    continue
                if result.status == AgentStatus.RUNNING:
                    continue
                if result.status == AgentStatus.COMPLETE:
                    if self._merge_task(task, sp):
                        task.status = TaskStatus.COMPLETE
                        task.agent_handle = None
                        self._observer.task_completed(
                            task_id=task.id,
                            spec_path=task.spec_path,
                            spec_blob_sha=task.spec_blob_sha,
                            cycle=self._cycle,
                        )
                        task.record_event(
                            reason=EventReason.TASK_COMPLETED,
                            message="Task completed and merged",
                            event_type=EventType.NORMAL,
                            timestamp=datetime.now(timezone.utc),
                        )
                        completed += 1
                    else:
                        self._mark_task_failed(task, "Merge resolution failed")
                        failed += 1
                elif result.status == AgentStatus.FAILED:
                    rationale = result.rationale or "Unknown failure"
                    self._mark_task_failed(task, rationale)
                    failed += 1
        return completed, failed

    def _mark_task_failed(self, task: Task, reason: str) -> None:
        task.agent_handle = None
        task.record_event(
            reason=EventReason.TASK_FAILED,
            message=reason,
            event_type=EventType.WARNING,
            timestamp=datetime.now(timezone.utc),
        )
        self._observer.task_failed(
            task_id=task.id,
            spec_path=task.spec_path,
            spec_blob_sha=task.spec_blob_sha,
            reason=reason,
            retry_count=task.retry_count,
            cycle=self._cycle,
        )
        if task.retry_count < self._max_task_retries:
            task.retry_count += 1
            task.status = TaskStatus.BACKLOG
            self._observer.task_retried(
                task_id=task.id,
                spec_path=task.spec_path,
                reason=reason,
                retry_count=task.retry_count,
                cycle=self._cycle,
            )
        else:
            task.status = TaskStatus.FAILED

    def _handle_retry_exhaustion(self, plan: Plan) -> None:
        for sp in plan.spec_plans:
            if sp.superseded or sp.status != SpecPlanStatus.RECONCILING:
                continue
            failed_tasks = [t for t in sp.tasks if t.status == TaskStatus.FAILED]
            if not failed_tasks:
                continue

            if sp.redecomposition_count < self._max_redecompositions:
                for task in sp.tasks:
                    if (
                        task.status == TaskStatus.IN_PROGRESS
                        and task.agent_handle is not None
                    ):
                        try:
                            self._agent_runtime.cancel(task.agent_handle)
                        except Exception:
                            pass
                        self._observer.agent_cancelled(
                            task_id=task.id,
                            spec_path=task.spec_path,
                            reason=CancellationReason.REDECOMPOSITION,
                        )
                sp.redecomposition_count += 1
                sp.status = SpecPlanStatus.OUT_OF_SYNC
                self._observer.redecomposition_triggered(
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    failed_task_count=len(failed_tasks),
                    cycle=self._cycle,
                )
            else:
                sp.status = SpecPlanStatus.FAILED
                self._observer.spec_failed(
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    reason="Task retry and re-decomposition budget exhausted",
                    cycle=self._cycle,
                )

    def _merge_task(self, task: Task, spec_plan: SpecPlan) -> bool:
        merge_result = self._workspace_manager.merge_task(task.spec_blob_sha, task.id)
        if merge_result.outcome == MergeOutcome.SUCCESS:
            self._observer.task_merge_completed(
                task_id=task.id, spec_blob_sha=task.spec_blob_sha
            )
            return True

        self._observer.task_merge_conflict(
            task_id=task.id, spec_blob_sha=task.spec_blob_sha
        )
        self._observer.merge_resolution_launched(
            task_id=task.id, spec_blob_sha=task.spec_blob_sha
        )
        success = self._agent_runtime.launch_merge_resolution(
            task.workspace_id or "",
            spec_plan.delivery_workspace_id or "",
            merge_result.conflict_details or "",
        )
        self._observer.merge_resolution_completed(
            task_id=task.id, spec_blob_sha=task.spec_blob_sha, success=success
        )
        if success:
            self._observer.task_merge_completed(
                task_id=task.id, spec_blob_sha=task.spec_blob_sha
            )
        return success

    def _launch_verification(self, plan: Plan) -> None:
        for sp in plan.spec_plans:
            if sp.superseded or sp.status != SpecPlanStatus.RECONCILING:
                continue
            if not all(t.status == TaskStatus.COMPLETE for t in sp.tasks):
                continue

            if sp.delivery_workspace_id is None:
                sp.delivery_workspace_id = (
                    self._workspace_manager.create_delivery_workspace(sp.blob_sha)
                )

            try:
                workspace_id = self._workspace_manager.create_verification_workspace(
                    sp.blob_sha
                )
                spec_content = self._spec_source.read_at(sp.path, sp.blob_sha)
                handle = self._agent_runtime.launch_verification(
                    spec_content, sp.path, sp.blob_sha, workspace_id
                )
            except Exception as exc:
                self._observer.verification_launch_failed(
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    reason=str(exc),
                    cycle=self._cycle,
                )
                continue
            sp.status = SpecPlanStatus.VERIFYING
            sp.verification_handle = handle
            self._observer.verification_launched(
                spec_path=sp.path,
                spec_blob_sha=sp.blob_sha,
                cycle=self._cycle,
            )

    def _collect_verification_results(self, plan: Plan) -> None:
        for sp in plan.spec_plans:
            if sp.superseded or sp.status != SpecPlanStatus.VERIFYING:
                continue

            if sp.verification_handle is None:
                self._retry_integration(sp)
                continue

            try:
                result = self._agent_runtime.poll(sp.verification_handle)
            except Exception:
                continue
            if result.status == AgentStatus.RUNNING:
                continue

            sp.verification_handle = None

            if result.verdict == AgentVerdict.PASS:
                rationale = result.rationale or "Verification passed"
                sp.record_event(
                    reason=EventReason.VERIFICATION_PASSED,
                    message=rationale,
                    event_type=EventType.NORMAL,
                    timestamp=datetime.now(timezone.utc),
                )
                self._observer.verification_passed(
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    rationale=rationale,
                    cycle=self._cycle,
                )
                self._integrate_to_trunk(sp)
            else:
                rationale = result.rationale or "Verification failed"
                sp.record_event(
                    reason=EventReason.VERIFICATION_FAILED,
                    message=rationale,
                    event_type=EventType.WARNING,
                    timestamp=datetime.now(timezone.utc),
                )
                self._observer.verification_failed(
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    rationale=rationale,
                    cycle=self._cycle,
                )
                self._workspace_manager.cleanup_verification(sp.blob_sha)
                sp.reconciliation_attempts += 1
                sp.redecomposition_count = 0
                if sp.reconciliation_attempts >= self._convergence_bound:
                    sp.status = SpecPlanStatus.FAILED
                    self._observer.spec_failed(
                        spec_path=sp.path,
                        spec_blob_sha=sp.blob_sha,
                        reason=f"Convergence bound ({self._convergence_bound}) exceeded",
                        cycle=self._cycle,
                    )
                else:
                    sp.status = SpecPlanStatus.OUT_OF_SYNC

    def _integrate_to_trunk(self, sp: SpecPlan) -> None:
        try:
            if sp.integration_summary is None:
                spec_content = self._spec_source.read_at(sp.path, sp.blob_sha)
                task_summaries = [
                    (t.name, t.description)
                    for t in sp.tasks
                    if t.status == TaskStatus.COMPLETE
                ]
                rationale = self._get_verification_rationale(sp)
                sp.integration_summary = (
                    self._agent_runtime.compose_integration_summary(
                        spec_content, task_summaries, rationale
                    )
                )

            integration_id = self._workspace_manager.integrate(
                sp.blob_sha,
                sp.path,
                sp.integration_summary.title,
                sp.integration_summary.body,
            )
            self._observer.trunk_integration_started(
                spec_path=sp.path,
                spec_blob_sha=sp.blob_sha,
                integration_id=integration_id,
            )
            sp.status = SpecPlanStatus.SYNCED
            sp.integration_attempts = 0
            self._observer.trunk_integration_completed(
                spec_path=sp.path,
                spec_blob_sha=sp.blob_sha,
                integration_id=integration_id,
            )
            self._observer.spec_synced(
                spec_path=sp.path,
                spec_blob_sha=sp.blob_sha,
                total_tasks=len(sp.tasks),
                cycle=self._cycle,
            )
            sp.record_event(
                reason=EventReason.SPEC_SYNCED,
                message=f"Integrated to trunk ({len(sp.tasks)} tasks)",
                event_type=EventType.NORMAL,
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as exc:
            sp.integration_attempts += 1
            reason = str(exc)
            sp.record_event(
                reason=EventReason.INTEGRATION_FAILED,
                message=reason,
                event_type=EventType.WARNING,
                timestamp=datetime.now(timezone.utc),
            )
            self._observer.trunk_integration_failed(
                spec_path=sp.path,
                spec_blob_sha=sp.blob_sha,
                reason=reason,
            )
            if sp.integration_attempts >= self._max_integration_retries:
                sp.status = SpecPlanStatus.FAILED
                self._observer.spec_failed(
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    reason=f"Integration retry limit ({self._max_integration_retries}) exceeded",
                    cycle=self._cycle,
                )

    def _get_verification_rationale(self, sp: SpecPlan) -> str:
        for event in reversed(sp.events):
            if event.reason == EventReason.VERIFICATION_PASSED:
                return event.message
        return ""

    def _retry_integration(self, sp: SpecPlan) -> None:
        has_passed = any(e.reason == EventReason.VERIFICATION_PASSED for e in sp.events)
        if has_passed:
            self._integrate_to_trunk(sp)

    def _detect_divergence(self, plan: Plan, entries: list[SpecEntry]) -> None:
        source_paths: set[str] = set()

        for entry in entries:
            source_paths.add(entry.path)
            existing = self._find_active_spec_plan(plan, entry.path)

            if existing is None:
                plan.add_spec(entry.path, entry.blob_sha)
                self._observer.spec_divergence_detected(
                    spec_path=entry.path,
                    blob_sha=entry.blob_sha,
                    change_type=ChangeType.NEW,
                )
            elif existing.blob_sha != entry.blob_sha:
                old_sha = existing.blob_sha
                self._cancel_superseded(existing)
                plan.add_spec(entry.path, entry.blob_sha)
                self._observer.spec_divergence_detected(
                    spec_path=entry.path,
                    blob_sha=entry.blob_sha,
                    change_type=ChangeType.MODIFIED,
                )
                self._observer.spec_superseded(
                    spec_path=entry.path,
                    old_sha=old_sha,
                    new_sha=entry.blob_sha,
                )

        for sp in plan.spec_plans:
            if sp.superseded:
                continue
            if sp.path not in source_paths:
                self._cancel_superseded(sp)
                sp.superseded = True
                self._observer.spec_divergence_detected(
                    spec_path=sp.path,
                    blob_sha=sp.blob_sha,
                    change_type=ChangeType.DELETED,
                )

    def _cancel_superseded(self, spec_plan: SpecPlan) -> None:
        for task in spec_plan.tasks:
            if task.status == TaskStatus.IN_PROGRESS and task.agent_handle is not None:
                try:
                    self._agent_runtime.cancel(task.agent_handle)
                except Exception:
                    pass
                self._observer.agent_cancelled(
                    task_id=task.id,
                    spec_path=task.spec_path,
                    reason=CancellationReason.SUPERSEDED,
                )

        if spec_plan.verification_handle is not None:
            try:
                self._agent_runtime.cancel(spec_plan.verification_handle)
            except Exception:
                pass

        self._workspace_manager.cleanup(spec_plan.blob_sha)

    def _invalidate_unsatisfiable_dependencies(self, plan: Plan) -> None:
        valid_task_ids: set[int] = set()
        for sp in plan.spec_plans:
            if sp.superseded:
                continue
            for task in sp.tasks:
                valid_task_ids.add(task.id)

        for sp in plan.spec_plans:
            if sp.superseded:
                continue
            for task in sp.tasks:
                if task.status in (TaskStatus.COMPLETE, TaskStatus.FAILED):
                    continue
                invalid_deps = [
                    dep_id for dep_id in task.depends_on if dep_id not in valid_task_ids
                ]
                if invalid_deps:
                    self._mark_dependency_invalidated(task, invalid_deps)

    def _mark_dependency_invalidated(
        self, task: Task, invalid_dep_ids: list[int]
    ) -> None:
        if task.status == TaskStatus.IN_PROGRESS and task.agent_handle is not None:
            try:
                self._agent_runtime.cancel(task.agent_handle)
            except Exception:
                pass
            self._observer.agent_cancelled(
                task_id=task.id,
                spec_path=task.spec_path,
                reason=CancellationReason.DEPENDENCY_INVALIDATED,
            )
        task.agent_handle = None
        task.status = TaskStatus.FAILED
        for dep_id in invalid_dep_ids:
            message = f"Dependency on task {dep_id} is unsatisfiable"
            task.record_event(
                reason=EventReason.DEPENDENCY_INVALIDATED,
                message=message,
                event_type=EventType.WARNING,
                timestamp=datetime.now(timezone.utc),
            )
            self._observer.dependency_invalidated(
                task_id=task.id,
                spec_path=task.spec_path,
                dependency_task_id=dep_id,
                reason=message,
            )

    def _find_active_spec_plan(self, plan: Plan, path: str) -> SpecPlan | None:
        for sp in plan.spec_plans:
            if sp.path == path and not sp.superseded:
                return sp
        return None

    def _count_out_of_sync(self, plan: Plan) -> int:
        return sum(
            1
            for sp in plan.spec_plans
            if not sp.superseded and sp.status == SpecPlanStatus.OUT_OF_SYNC
        )

    @staticmethod
    def _format_workspace_briefing(task: Task) -> str:
        lines = [
            f"Task {task.id}: {task.name}",
            "",
            task.description,
            "",
            f"Spec: {task.spec_path} @ {task.spec_blob_sha}",
        ]
        if task.events:
            lines.append("")
            lines.append("Events:")
            for event in task.events:
                lines.append(f"- [{event.type}] {event.reason}: {event.message}")
        return "\n".join(lines)

    def _count_in_progress(self, plan: Plan) -> int:
        return sum(
            1
            for sp in plan.spec_plans
            if not sp.superseded
            for t in sp.tasks
            if t.status == TaskStatus.IN_PROGRESS
        )
