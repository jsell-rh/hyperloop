from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class EventType(StrEnum):
    NORMAL = "Normal"
    WARNING = "Warning"


class SpecPlanStatus(StrEnum):
    OUT_OF_SYNC = "OutOfSync"
    RECONCILING = "Reconciling"
    VERIFYING = "Verifying"
    SYNCED = "Synced"
    FAILED = "Failed"


class TaskStatus(StrEnum):
    BACKLOG = "Backlog"
    IN_PROGRESS = "InProgress"
    COMPLETE = "Complete"
    FAILED = "Failed"


class Event(BaseModel):
    type: EventType
    reason: str
    count: int = 1
    first_timestamp: datetime
    last_timestamp: datetime
    message: str


def _record_event(
    events: list[Event],
    *,
    reason: str,
    message: str,
    event_type: EventType,
    timestamp: datetime,
) -> None:
    for event in events:
        if event.reason == reason:
            event.count += 1
            event.last_timestamp = timestamp
            event.message = message
            return
    events.append(
        Event(
            type=event_type,
            reason=reason,
            count=1,
            first_timestamp=timestamp,
            last_timestamp=timestamp,
            message=message,
        )
    )


class Task(BaseModel):
    id: int
    depends_on: list[int] = []
    spec_path: str
    spec_blob_sha: str
    name: str
    description: str
    status: TaskStatus = TaskStatus.BACKLOG
    events: list[Event] = []

    def record_event(
        self,
        *,
        reason: str,
        message: str,
        event_type: EventType,
        timestamp: datetime,
    ) -> None:
        _record_event(self.events, reason=reason, message=message, event_type=event_type, timestamp=timestamp)


class SpecPlan(BaseModel):
    path: str
    blob_sha: str
    status: SpecPlanStatus = SpecPlanStatus.OUT_OF_SYNC
    superseded: bool = False
    reconciliation_attempts: int = 0
    has_redecomposed: bool = False
    tasks: list[Task] = []
    events: list[Event] = []

    def record_event(
        self,
        *,
        reason: str,
        message: str,
        event_type: EventType,
        timestamp: datetime,
    ) -> None:
        _record_event(self.events, reason=reason, message=message, event_type=event_type, timestamp=timestamp)

    def record_verification_failure(self) -> None:
        self.reconciliation_attempts += 1
        self.has_redecomposed = False
        self.status = SpecPlanStatus.OUT_OF_SYNC


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
        _record_event(self.events, reason=reason, message=message, event_type=event_type, timestamp=timestamp)

    def add_spec(self, path: str, blob_sha: str) -> SpecPlan:
        for sp in self.spec_plans:
            if sp.path == path and sp.blob_sha == blob_sha:
                return sp

        for sp in self.spec_plans:
            if sp.path == path:
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
