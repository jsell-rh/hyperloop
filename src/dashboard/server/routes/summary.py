"""GET /api/summary — aggregate task counts."""

from __future__ import annotations

from fastapi import APIRouter

from dashboard.server.deps import get_state
from dashboard.server.models import SummaryResponse

router = APIRouter()


def _status_str(status_enum: object) -> str:
    """Convert a TaskStatus enum to its kebab-case string."""
    return str(status_enum.value).replace("_", "-")  # type: ignore[union-attr]


@router.get("/api/summary")
def summary(repo: str | None = None) -> SummaryResponse:
    """Return aggregate progress counts across all tasks."""
    world = get_state().get_world()
    tasks = list(world.tasks.values())

    counts = {"not-started": 0, "in-progress": 0, "completed": 0, "failed": 0}
    for task in tasks:
        status_key = _status_str(task.status)
        if status_key in counts:
            counts[status_key] += 1

    # Group tasks by unversioned spec_ref
    specs: dict[str, list[str]] = {}
    for task in tasks:
        base_ref = task.spec_ref.split("@")[0]
        specs.setdefault(base_ref, []).append(_status_str(task.status))

    # A spec is "complete" when all tasks are terminal and at least one is completed
    terminal = {"completed", "failed"}
    specs_complete = 0
    for statuses in specs.values():
        if all(s in terminal for s in statuses) and "completed" in statuses:
            specs_complete += 1

    return SummaryResponse(
        total=len(tasks),
        not_started=counts["not-started"],
        in_progress=counts["in-progress"],
        complete=counts["completed"],
        failed=counts["failed"],
        specs_total=len(specs),
        specs_complete=specs_complete,
    )
