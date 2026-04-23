"""GET /api/tasks — task listing and detail endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from dashboard.server.agents_loader import load_agent_templates
from dashboard.server.deps import get_repo_path, get_state
from dashboard.server.models import (
    DepDetail,
    GraphEdge,
    GraphNode,
    GraphResponse,
    PromptSectionResponse,
    ReconstructedPrompt,
    Review,
    TaskDetail,
    TaskSummary,
)
from dashboard.server.reviews import read_reviews

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

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
        pr_title=task.pr_title,
        pr_description=task.pr_description,
    )


def _resolve_deps_detail(dep_ids: tuple[str, ...]) -> list[DepDetail]:
    """Look up each dependency task and return summary info.

    Missing deps are silently skipped — the task may reference a dep that
    has been deleted or is not yet visible.
    """
    state = get_state()
    world = state.get_world()
    details: list[DepDetail] = []
    for dep_id in dep_ids:
        dep_task = world.tasks.get(dep_id)
        if dep_task is not None:
            details.append(
                DepDetail(
                    id=dep_task.id,
                    title=dep_task.title,
                    status=_status_str(dep_task.status),
                )
            )
        else:
            details.append(DepDetail(id=dep_id, title="(unknown)", status="not-started"))
    return details


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


def _compute_critical_path(tasks: Mapping[str, object]) -> list[str]:
    """Find the longest chain of non-terminal tasks using DFS.

    Builds an adjacency list (dep -> dependents) and finds the longest
    path through tasks that are not complete or failed.
    """
    from hyperloop.domain.model import Task, TaskStatus

    # Build adjacency: from dep_id -> list of dependent task ids
    adjacency: dict[str, list[str]] = {}
    non_terminal_ids: set[str] = set()

    for task_id, task in tasks.items():
        assert isinstance(task, Task)
        if task.status not in (TaskStatus.COMPLETE, TaskStatus.FAILED):
            non_terminal_ids.add(task_id)

    for task_id, task in tasks.items():
        assert isinstance(task, Task)
        if task_id not in non_terminal_ids:
            continue
        for dep_id in task.deps:
            if dep_id in non_terminal_ids:
                adjacency.setdefault(dep_id, []).append(task_id)

    # Find roots: non-terminal tasks with no non-terminal deps
    roots: list[str] = []
    for task_id in non_terminal_ids:
        task = tasks[task_id]
        assert isinstance(task, Task)
        has_non_terminal_dep = any(d in non_terminal_ids for d in task.deps)
        if not has_non_terminal_dep:
            roots.append(task_id)

    # DFS longest path from each root
    memo: dict[str, list[str]] = {}

    def longest_from(node_id: str) -> list[str]:
        if node_id in memo:
            return memo[node_id]
        children = adjacency.get(node_id, [])
        best: list[str] = []
        for child in children:
            candidate = longest_from(child)
            if len(candidate) > len(best):
                best = candidate
        result = [node_id, *best]
        memo[node_id] = result
        return result

    overall_best: list[str] = []
    for root in roots:
        path = longest_from(root)
        if len(path) > len(overall_best):
            overall_best = path

    return overall_best


@router.get("/api/tasks/graph")
def get_task_graph() -> GraphResponse:
    """Return the full dependency graph with critical path for visualization."""
    world = get_state().get_world()
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    for task in world.tasks.values():
        nodes.append(
            GraphNode(
                id=task.id,
                title=task.title,
                status=_status_str(task.status),
                phase=str(task.phase) if task.phase else None,
                spec_ref=task.spec_ref.split("@")[0],
                round=task.round,
            )
        )
        for dep in task.deps:
            edges.append(GraphEdge(from_id=dep, to_id=task.id))

    critical_path = _compute_critical_path(world.tasks)
    return GraphResponse(nodes=nodes, edges=edges, critical_path=critical_path)


@router.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> TaskDetail:
    """Return full task detail with review history and dependency info."""
    try:
        task = get_state().get_task(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")  # noqa: B904

    reviews: list[Review] = read_reviews(get_repo_path(), task_id)
    deps_detail = _resolve_deps_detail(task.deps)

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
        deps_detail=deps_detail,
        reviews=reviews,
    )


# ---------------------------------------------------------------------------
# Prompt reconstruction
# ---------------------------------------------------------------------------


def _load_agent_templates(repo_path: Path) -> dict[str, dict[str, str]]:
    """Load agent templates via kustomize build, falling back to raw YAML files.

    Delegates to the shared agents_loader module.
    """
    return load_agent_templates(repo_path)


@router.get("/api/tasks/{task_id}/prompt")
def get_task_prompt(task_id: str) -> list[ReconstructedPrompt]:
    """Reconstruct the prompt that would be composed for a task.

    This reads the agent templates + task context and assembles the
    prompt sections with source provenance, mirroring compose.py logic
    without requiring kustomize.
    """
    state = get_state()
    repo_path = get_repo_path()

    try:
        task = state.get_task(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")  # noqa: B904

    templates = _load_agent_templates(repo_path)
    if not templates:
        return []

    # Read spec content
    spec_ref = task.spec_ref
    spec_path = spec_ref.split("@")[0] if "@" in spec_ref else spec_ref
    spec_content = state.read_file(spec_path)

    # Read findings
    findings = state.get_findings(task_id)

    # Determine which roles to reconstruct: the task's current phase
    # plus common pipeline roles
    roles_to_show: list[str] = []
    # Show the current phase role if it maps to an agent template
    if task.phase is not None and str(task.phase) in templates:
        roles_to_show.append(str(task.phase))
    # Also include all agent templates that are relevant to task pipelines
    for role_name in templates:
        if role_name not in roles_to_show:
            roles_to_show.append(role_name)

    results: list[ReconstructedPrompt] = []
    for role in roles_to_show:
        tmpl = templates.get(role)
        if tmpl is None:
            continue

        sections: list[PromptSectionResponse] = []

        # Template prompt with variable substitution
        prompt_text = (
            tmpl["prompt"]
            .replace("{spec_ref}", spec_ref)
            .replace("{task_id}", task_id)
            .replace("{round}", str(task.round))
        )
        sections.append(
            PromptSectionResponse(source="base", label="prompt", content=prompt_text.rstrip())
        )

        # Guidelines
        if tmpl["guidelines"]:
            sections.append(
                PromptSectionResponse(
                    source="process-overlay",
                    label="guidelines",
                    content=tmpl["guidelines"],
                )
            )

        # Spec content
        if spec_content is not None:
            sections.append(
                PromptSectionResponse(source="spec", label="spec", content=spec_content)
            )
        else:
            sections.append(
                PromptSectionResponse(
                    source="spec",
                    label="spec",
                    content=f"[Spec file '{spec_ref}' not found.]",
                )
            )

        # Findings
        if findings:
            sections.append(
                PromptSectionResponse(source="findings", label="findings", content=findings)
            )

        results.append(ReconstructedPrompt(role=role, sections=sections))

    return results
