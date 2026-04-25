"""GET /api/pipeline — pipeline step definitions (flat phase list)."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import yaml
from fastapi import APIRouter

from dashboard.server.deps import get_repo_path
from dashboard.server.models import PipelineStepInfo

if TYPE_CHECKING:
    from pathlib import Path

router = APIRouter()


def _flatten_steps(steps: list[object]) -> list[PipelineStepInfo]:
    """Walk a pipeline definition and flatten steps into an ordered list.

    Loop steps are recursed into; each child appears in order.  The step
    ``type`` is derived from whichever primitive key (agent/gate/action/loop)
    is present.
    """
    result: list[PipelineStepInfo] = []
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            continue
        step = cast("dict[str, object]", raw_step)
        if "agent" in step:
            result.append(PipelineStepInfo(name=str(step["agent"]), type="agent"))
        elif "gate" in step:
            result.append(PipelineStepInfo(name=str(step["gate"]), type="gate"))
        elif "check" in step:
            result.append(PipelineStepInfo(name=str(step["check"]), type="check"))
        elif "action" in step:
            result.append(PipelineStepInfo(name=str(step["action"]), type="action"))
        elif "loop" in step:
            children = step["loop"]
            if isinstance(children, list):
                result.extend(_flatten_steps(cast("list[object]", children)))
    return result


def _steps_from_phases(phases: dict[str, object]) -> list[PipelineStepInfo]:
    """Build an ordered step list from a flat phases dict.

    Each phase entry has a ``run`` key that may be prefixed with a type
    (e.g. ``gate:pr_checks``).  If no prefix, the type defaults to
    ``agent``.
    """
    result: list[PipelineStepInfo] = []
    for name, cfg in phases.items():
        step_type = "agent"
        if isinstance(cfg, dict):
            run = cast("dict[str, str]", cfg).get("run", name)
            colon = run.find(":")
            if colon > 0:
                step_type = run[:colon]
        result.append(PipelineStepInfo(name=name, type=step_type))
    return result


def _load_pipeline_steps(repo_path: Path) -> list[PipelineStepInfo]:
    """Read the process definition and return flattened pipeline steps.

    Supports both the new flat ``phases`` key and the legacy ``pipeline``
    list.  Tries the repo-local process.yaml first, then falls back to
    ``base/process.yaml`` (the hyperloop default).
    """
    candidates = [
        repo_path / ".hyperloop" / "agents" / "process" / "process.yaml",
        repo_path / ".hyperloop" / "agents" / "process.yaml",
        repo_path / "base" / "process.yaml",
    ]

    for path in candidates:
        if path.exists():
            with open(path) as f:
                docs = list(yaml.safe_load_all(f))
            for doc in docs:
                if isinstance(doc, dict):
                    typed_doc = cast("dict[str, object]", doc)
                    if typed_doc.get("kind") == "Process":
                        # New format: flat phases dict
                        phases_raw = typed_doc.get("phases")
                        if isinstance(phases_raw, dict):
                            return _steps_from_phases(
                                cast("dict[str, object]", phases_raw),
                            )
                        # Legacy format: pipeline list
                        pipeline_raw = typed_doc.get("pipeline")
                        if isinstance(pipeline_raw, list):
                            return _flatten_steps(cast("list[object]", pipeline_raw))
    return []


@router.get("/api/pipeline")
def get_pipeline() -> list[PipelineStepInfo]:
    """Return the pipeline steps in order, flattened from the process definition."""
    return _load_pipeline_steps(get_repo_path())
