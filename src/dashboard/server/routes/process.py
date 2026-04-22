"""GET /api/process — pipeline, gates, actions, hooks, and process learning."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import yaml
from fastapi import APIRouter

if TYPE_CHECKING:
    from pathlib import Path

from dashboard.server.deps import get_repo_path
from dashboard.server.models import (
    PipelineTreeStep,
    ProcessLearning,
    ProcessResponse,
)

router = APIRouter()


def _find_process_yaml_path(repo_path: Path) -> Path | None:
    """Locate the process.yaml file, checking common locations."""
    candidates = [
        repo_path / ".hyperloop" / "agents" / "process" / "process.yaml",
        repo_path / ".hyperloop" / "agents" / "process.yaml",
        repo_path / "base" / "process.yaml",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _find_and_read_process_yaml(repo_path: Path) -> dict[str, object]:
    """Read and parse the process.yaml, returning its contents as a dict.

    Returns an empty dict if no process.yaml is found.
    """
    path = _find_process_yaml_path(repo_path)
    if path is None:
        return {}

    try:
        with open(path) as f:
            docs = list(yaml.safe_load_all(f))
    except (yaml.YAMLError, OSError):
        return {}

    for doc in docs:
        if isinstance(doc, dict):
            typed_doc = cast("dict[str, object]", doc)
            if typed_doc.get("kind") == "Process":
                return typed_doc

    # If no Process kind found, return the first doc if it's a dict
    if docs and isinstance(docs[0], dict):
        return cast("dict[str, object]", docs[0])

    return {}


def _parse_pipeline_tree(steps: list[object]) -> list[PipelineTreeStep]:
    """Parse the pipeline definition into a nested tree structure.

    Preserves loop nesting so the frontend can render grouped steps.
    """
    result: list[PipelineTreeStep] = []
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            continue
        step = cast("dict[str, object]", raw_step)
        if "agent" in step:
            result.append(PipelineTreeStep(type="agent", name=str(step["agent"])))
        elif "gate" in step:
            result.append(PipelineTreeStep(type="gate", name=str(step["gate"])))
        elif "action" in step:
            result.append(PipelineTreeStep(type="action", name=str(step["action"])))
        elif "loop" in step:
            children = step["loop"]
            child_steps: list[PipelineTreeStep] = []
            if isinstance(children, list):
                child_steps = _parse_pipeline_tree(cast("list[object]", children))
            result.append(PipelineTreeStep(type="loop", children=child_steps))
    return result


def _read_process_learning(repo_path: Path) -> ProcessLearning:
    """Read process overlay files to discover what the process-improver has learned.

    Looks for *-overlay.yaml files in .hyperloop/agents/process/ and extracts
    guidelines for each agent.
    """
    overlay_dir = repo_path / ".hyperloop" / "agents" / "process"
    patched_agents: list[str] = []
    guidelines: dict[str, str] = {}

    if not overlay_dir.is_dir():
        return ProcessLearning(patched_agents=[], guidelines={})

    for overlay_file in sorted(overlay_dir.glob("*-overlay.yaml")):
        try:
            with open(overlay_file) as f:
                doc = yaml.safe_load(f)
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(doc, dict):
            continue
        typed_doc = cast("dict[str, object]", doc)

        # Extract agent name from filename (e.g., "implementer-overlay.yaml" -> "implementer")
        agent_name = overlay_file.stem.replace("-overlay", "")
        agent_guidelines = typed_doc.get("guidelines", "")
        if isinstance(agent_guidelines, str) and agent_guidelines.strip():
            patched_agents.append(agent_name)
            guidelines[agent_name] = agent_guidelines.strip()

    return ProcessLearning(patched_agents=patched_agents, guidelines=guidelines)


def _read_kustomization_refs(repo_path: Path) -> dict[str, str | None]:
    """Read kustomization.yaml for source refs."""
    candidates = [
        repo_path / ".hyperloop" / "agents" / "kustomization.yaml",
        repo_path / "kustomization.yaml",
    ]

    for path in candidates:
        if not path.exists():
            continue
        try:
            with open(path) as f:
                doc = yaml.safe_load(f)
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(doc, dict):
            continue
        typed_doc = cast("dict[str, object]", doc)

        # Look for resources or bases entries with remote refs
        resources = typed_doc.get("resources", [])
        if isinstance(resources, list) and resources:
            # The first resource is typically the base ref
            res_list = cast("list[object]", resources)
            return {"base_ref": str(res_list[0])}

    return {"base_ref": None}


@router.get("/api/process")
def get_process() -> ProcessResponse:
    """Return the full process definition with learning state."""
    repo_path = get_repo_path()

    process_yaml = _find_and_read_process_yaml(repo_path)

    # Parse pipeline tree
    pipeline_raw_list = process_yaml.get("pipeline", [])
    pipeline_steps = _parse_pipeline_tree(
        cast("list[object]", pipeline_raw_list) if isinstance(pipeline_raw_list, list) else []
    )

    # Raw YAML for display
    pipeline_raw = yaml.dump(
        pipeline_raw_list if isinstance(pipeline_raw_list, list) else [],
        default_flow_style=False,
    )

    # Gate/action/hook configs
    gates_raw = process_yaml.get("gates", {})
    actions_raw = process_yaml.get("actions", {})
    hooks_raw = process_yaml.get("hooks", {})

    gates = cast("dict[str, object]", gates_raw) if isinstance(gates_raw, dict) else {}
    actions = cast("dict[str, object]", actions_raw) if isinstance(actions_raw, dict) else {}
    hooks = cast("dict[str, object]", hooks_raw) if isinstance(hooks_raw, dict) else {}

    # Process learning
    process_learning = _read_process_learning(repo_path)

    # Source info
    process_path = _find_process_yaml_path(repo_path)
    source_file = str(process_path) if process_path else ""
    kustomization = _read_kustomization_refs(repo_path)

    return ProcessResponse(
        pipeline_steps=pipeline_steps,
        pipeline_raw=pipeline_raw,
        gates=gates,
        actions=actions,
        hooks=hooks,
        process_learning=process_learning,
        source_file=source_file,
        base_ref=kustomization.get("base_ref"),
    )
