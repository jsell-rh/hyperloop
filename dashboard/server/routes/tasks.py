"""GET /api/tasks — task listing and detail endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dashboard.server.deps import get_repo_path, get_state
from dashboard.server.models import Review, TaskDetail, TaskSummary
from dashboard.server.reviews import read_reviews

router = APIRouter()


def _status_str(status_enum: object) -> str:
    """Convert a TaskStatus enum to its kebab-case string."""
    return str(status_enum.value).replace("_", "-")  # type: ignore[union-attr]


def _task_to_summary(task: object) -> TaskSummary:
    """Convert a domain Task to a TaskSummary response model."""
    from hyperloop.domain.model import Task

    assert isinstance(task, Task)
    return TaskSummary(
        id=task.id,
        title=task.title,
        status=_status_str(task.status),
        phase=str(task.phase) if task.phase is not None else None,
        round=task.round,
        branch=task.branch,
        pr=task.pr,
        spec_ref=task.spec_ref,
    )


@router.get("/api/tasks")
def list_tasks(
    status: str | None = None,
    spec_ref: str | None = None,
) -> list[TaskSummary]:
    """List all tasks, optionally filtered by status or spec_ref prefix."""
    world = get_state().get_world()
    tasks = list(world.tasks.values())

    if status is not None:
        tasks = [t for t in tasks if _status_str(t.status) == status]

    if spec_ref is not None:
        tasks = [t for t in tasks if t.spec_ref.split("@")[0] == spec_ref]

    return [_task_to_summary(t) for t in tasks]


@router.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> TaskDetail:
    """Return full task detail with review history."""
    try:
        task = get_state().get_task(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")  # noqa: B904

    reviews: list[Review] = read_reviews(get_repo_path(), task_id)

    return TaskDetail(
        id=task.id,
        title=task.title,
        status=_status_str(task.status),
        phase=str(task.phase) if task.phase is not None else None,
        round=task.round,
        branch=task.branch,
        pr=task.pr,
        spec_ref=task.spec_ref,
        deps=list(task.deps),
        reviews=reviews,
    )
