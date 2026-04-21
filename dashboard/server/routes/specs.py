"""GET /api/specs — spec listing and detail endpoints."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from dashboard.server.deps import get_spec_source, get_state
from dashboard.server.models import SpecDetail, SpecSummary, TaskSummary

router = APIRouter()


def _status_str(status_enum: object) -> str:
    """Convert a TaskStatus enum to its kebab-case string."""
    return str(status_enum.value).replace("_", "-")  # type: ignore[union-attr]


def _extract_title(content: str) -> str:
    """Extract the first markdown heading from spec content."""
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else "(untitled)"


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


@router.get("/api/specs")
def list_specs() -> list[SpecSummary]:
    """List all specs with task progress summary.

    Finds spec files via StateStore.list_files, reads content via SpecSource
    for titles, and groups tasks by unversioned spec_ref.
    """
    state = get_state()
    spec_source = get_spec_source()

    # Get all tasks and group by unversioned spec_ref
    world = state.get_world()
    spec_tasks: dict[str, list[str]] = {}
    for task in world.tasks.values():
        base_ref = task.spec_ref.split("@")[0]
        spec_tasks.setdefault(base_ref, []).append(_status_str(task.status))

    # Find all spec files
    spec_files = state.list_files("specs/*.md")

    results: list[SpecSummary] = []
    for spec_path in spec_files:
        content = spec_source.read(spec_path)
        title = _extract_title(content)
        statuses = spec_tasks.get(spec_path, [])

        results.append(
            SpecSummary(
                spec_ref=spec_path,
                title=title,
                tasks_total=len(statuses),
                tasks_complete=statuses.count("complete"),
                tasks_in_progress=statuses.count("in-progress"),
                tasks_failed=statuses.count("failed"),
                tasks_not_started=statuses.count("not-started"),
            )
        )

    # Include specs that have tasks but no spec file on disk
    for spec_ref, statuses in spec_tasks.items():
        if spec_ref not in spec_files:
            content = spec_source.read(spec_ref)
            title = _extract_title(content) if content else "(untitled)"
            results.append(
                SpecSummary(
                    spec_ref=spec_ref,
                    title=title,
                    tasks_total=len(statuses),
                    tasks_complete=statuses.count("complete"),
                    tasks_in_progress=statuses.count("in-progress"),
                    tasks_failed=statuses.count("failed"),
                    tasks_not_started=statuses.count("not-started"),
                )
            )

    return results


@router.get("/api/specs/{spec_ref:path}")
def get_spec(spec_ref: str) -> SpecDetail:
    """Return spec content and associated tasks.

    The spec_ref in the URL is the unversioned spec path (e.g. specs/persistence.md).
    Tasks are matched by their spec_ref starting with this path.
    """
    spec_source = get_spec_source()
    state = get_state()

    content = spec_source.read(spec_ref)
    if not content:
        raise HTTPException(status_code=404, detail=f"Spec {spec_ref} not found")

    world = state.get_world()
    matching_tasks = [
        _task_to_summary(task)
        for task in world.tasks.values()
        if task.spec_ref.split("@")[0] == spec_ref
    ]

    return SpecDetail(
        spec_ref=spec_ref,
        content=content,
        tasks=matching_tasks,
    )
