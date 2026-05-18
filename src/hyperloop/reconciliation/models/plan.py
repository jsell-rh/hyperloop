from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from hyperloop.reconciliation.models.event import Event, EventType, record_event
from hyperloop.reconciliation.models.spec_plan import SpecPlan, SpecPlanStatus
from hyperloop.reconciliation.models.task import Task, TaskStatus


class Plan(BaseModel):
    spec_plans: list[SpecPlan] = []
    events: list[Event] = []
    task_id_counter: int = 0

    def record_event(
        self,
        *,
        reason: str,
        message: str,
        event_type: EventType,
        timestamp: datetime,
    ) -> None:
        record_event(
            self.events,
            reason=reason,
            message=message,
            event_type=event_type,
            timestamp=timestamp,
        )

    def add_spec(self, path: str, blob_sha: str) -> SpecPlan:
        for sp in self.spec_plans:
            if sp.path == path and sp.blob_sha == blob_sha:
                return sp

        for sp in self.spec_plans:
            if sp.path == path and sp.status != SpecPlanStatus.SYNCED:
                sp.superseded = True

        new_sp = SpecPlan(path=path, blob_sha=blob_sha)
        self.spec_plans.append(new_sp)
        return new_sp

    def next_task_id(self) -> int:
        self.task_id_counter += 1
        return self.task_id_counter

    def add_tasks(self, spec_plan: SpecPlan, tasks: list[Task]) -> None:
        spec_plan.tasks.extend(tasks)
        spec_plan.status = SpecPlanStatus.RECONCILING

    def get_unblocked_tasks(self) -> list[Task]:
        completed_ids: set[int] = set()
        for sp in self.spec_plans:
            for task in sp.tasks:
                if task.status == TaskStatus.COMPLETE:
                    completed_ids.add(task.id)

        result: list[Task] = []
        for sp in self.spec_plans:
            if sp.superseded:
                continue
            for task in sp.tasks:
                if task.status != TaskStatus.BACKLOG:
                    continue
                if all(dep_id in completed_ids for dep_id in task.depends_on):
                    result.append(task)
        return result
