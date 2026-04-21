"""GET /api/tasks — task listing and detail endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from fastapi import APIRouter, HTTPException

from dashboard.server.deps import get_repo_path, get_state
from dashboard.server.models import (
    DepDetail,
    PromptSectionResponse,
    ReconstructedPrompt,
    Review,
    TaskDetail,
    TaskSummary,
)
from dashboard.server.reviews import read_reviews

if TYPE_CHECKING:
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

    Tries kustomize build first (resolves remote refs), then falls back to
    reading local YAML files directly.
    """
    import subprocess

    templates: dict[str, dict[str, str]] = {}

    # Try kustomize build (resolves remote base refs)
    overlay_dir = repo_path / ".hyperloop" / "agents"
    if overlay_dir.is_dir():
        result = subprocess.run(
            ["kustomize", "build", str(overlay_dir)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            for doc in yaml.safe_load_all(result.stdout):
                if not isinstance(doc, dict) or doc.get("kind") != "Agent":
                    continue
                metadata = doc.get("metadata", {})
                name = metadata.get("name", "") if isinstance(metadata, dict) else ""
                if not name:
                    name = str(doc.get("name", ""))
                if not name:
                    continue
                templates[name] = {
                    "prompt": str(doc.get("prompt", "")),
                    "guidelines": str(doc.get("guidelines", "")).strip(),
                }
            if templates:
                return templates

    # Fallback: read raw YAML files from base/
    base_dir = repo_path / "base"
    if not base_dir.is_dir():
        return templates

    for yaml_file in base_dir.glob("*.yaml"):
        if yaml_file.name == "kustomization.yaml":
            continue
        try:
            with open(yaml_file) as f:
                doc = yaml.safe_load(f)
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(doc, dict) or doc.get("kind") != "Agent":
            continue
        metadata = doc.get("metadata", {})
        name = metadata.get("name", "") if isinstance(metadata, dict) else ""
        if not name:
            name = str(doc.get("name", ""))
        if not name:
            continue
        templates[name] = {
            "prompt": str(doc.get("prompt", "")),
            "guidelines": str(doc.get("guidelines", "")).strip(),
        }
    return templates


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
