from __future__ import annotations

from hyperloop.reconciliation.models.event import Event
from hyperloop.reconciliation.models.spec_plan import SpecPlan
from hyperloop.reconciliation.models.task import Task, TaskStatus


def spec_plan_to_dict(
    sp: SpecPlan, *, include_events: bool = False
) -> dict[str, object]:
    result: dict[str, object] = {
        "path": sp.path,
        "blob_sha": sp.blob_sha,
        "status": spec_display_status(sp),
        "superseded": sp.superseded,
        "reconciliation_attempts": sp.reconciliation_attempts,
        "redecomposition_count": sp.redecomposition_count,
        "tasks": [task_to_dict(t, include_events=include_events) for t in sp.tasks],
    }
    if include_events:
        result["events"] = [event_to_dict(e) for e in sp.events]
    return result


def task_to_dict(t: Task, *, include_events: bool = False) -> dict[str, object]:
    result: dict[str, object] = {
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "spec_path": t.spec_path,
        "spec_blob_sha": t.spec_blob_sha,
        "status": t.status.value,
        "depends_on": t.depends_on,
        "retry_count": t.retry_count,
    }
    if include_events:
        result["events"] = [event_to_dict(e) for e in t.events]
    return result


def event_to_dict(event: Event, *, obj_ref: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "type": event.type.value,
        "reason": event.reason,
        "count": event.count,
        "first_timestamp": event.first_timestamp.isoformat(),
        "last_timestamp": event.last_timestamp.isoformat(),
        "message": event.message,
    }
    if obj_ref is not None:
        result["object"] = obj_ref
    return result


def spec_display_status(sp: SpecPlan) -> str:
    if sp.superseded:
        return "Superseded"
    return sp.status.value


def completed_count(sp: SpecPlan) -> int:
    return sum(1 for t in sp.tasks if t.status == TaskStatus.COMPLETE)
