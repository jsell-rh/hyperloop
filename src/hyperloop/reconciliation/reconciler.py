from __future__ import annotations

import time

from hyperloop.reconciliation.models.cancellation_reason import CancellationReason
from hyperloop.reconciliation.models.event import Event
from hyperloop.reconciliation.models.plan import Plan
from hyperloop.reconciliation.models.proposed_task import ProposedTask
from hyperloop.reconciliation.models.spec_diff import SpecDiff
from hyperloop.reconciliation.models.spec_entry import SpecEntry
from hyperloop.reconciliation.models.spec_plan import SpecPlan, SpecPlanStatus
from hyperloop.reconciliation.models.task import Task, TaskStatus
from hyperloop.reconciliation.ports.agent_runtime import AgentRuntime
from hyperloop.reconciliation.ports.observer import ChangeType, Observer
from hyperloop.reconciliation.ports.plan_store import PlanStore
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
    ) -> None:
        self._spec_source = spec_source
        self._plan_store = plan_store
        self._observer = observer
        self._agent_runtime = agent_runtime
        self._workspace_manager = workspace_manager
        self._cycle: int = 0

    def run_cycle(self) -> None:
        self._cycle += 1
        start = time.monotonic()

        self._spec_source.sync()
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
        self._decompose(plan)

        self._plan_store.write_plan(plan)
        self._observer.plan_synced(cycle=self._cycle)

        duration = time.monotonic() - start
        self._observer.cycle_completed(
            cycle=self._cycle,
            duration_s=duration,
            specs_out_of_sync=self._count_out_of_sync(plan),
            tasks_dispatched=0,
            tasks_completed=0,
            tasks_failed=0,
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
            diff_text = self._spec_source.diff(sp.path, old_sha, sp.blob_sha)
            spec_diffs.append(
                SpecDiff(spec_path=sp.path, blob_sha=sp.blob_sha, diff_text=diff_text)
            )

        existing_tasks = self._collect_all_tasks(plan)
        events = self._collect_spec_events(out_of_sync)

        proposed = self._agent_runtime.launch_decomposition(
            spec_diffs, existing_tasks, events
        )

        tasks_created = self._materialize_tasks(plan, out_of_sync, proposed)

        duration = time.monotonic() - start
        self._observer.decomposition_completed(
            specs_count=len(out_of_sync),
            tasks_created=tasks_created,
            cycle=self._cycle,
            duration_s=duration,
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

    def _count_in_progress(self, plan: Plan) -> int:
        return sum(
            1
            for sp in plan.spec_plans
            if not sp.superseded
            for t in sp.tasks
            if t.status == TaskStatus.IN_PROGRESS
        )
