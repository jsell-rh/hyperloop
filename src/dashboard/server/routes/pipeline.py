"""GET /api/pipeline — pipeline step definitions."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import yaml
from fastapi import APIRouter

from dashboard.server.deps import get_repo_path
from dashboard.server.models import PipelineStepInfo

if TYPE_CHECKING:
    from pathlib import Path

router = APIRouter()


def _flatten_steps(steps: list[object], *, in_loop: bool = False) -> list[PipelineStepInfo]:
    """Walk a pipeline definition and flatten steps into an ordered list.

    Loop steps are recursed into; each child appears in order.  The step
    ``type`` is derived from whichever primitive key (agent/gate/action/loop)
    is present.  Steps inside a ``loop:`` block are tagged with
    ``in_loop=True`` so the frontend can visually group them.
    """
    result: list[PipelineStepInfo] = []
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            continue
        step = cast("dict[str, object]", raw_step)
        if "agent" in step:
            result.append(PipelineStepInfo(name=str(step["agent"]), type="agent", in_loop=in_loop))
        elif "gate" in step:
            result.append(PipelineStepInfo(name=str(step["gate"]), type="gate", in_loop=in_loop))
        elif "action" in step:
            result.append(
                PipelineStepInfo(name=str(step["action"]), type="action", in_loop=in_loop)
            )
        elif "loop" in step:
            children = step["loop"]
            if isinstance(children, list):
                result.extend(_flatten_steps(cast("list[object]", children), in_loop=True))
    return result


def _load_pipeline_steps(repo_path: Path) -> list[PipelineStepInfo]:
    """Read the process definition and return flattened pipeline steps.

    Tries the repo-local ``.hyperloop/agents/process/process.yaml`` first,
    then falls back to ``base/process.yaml`` (the hyperloop default).
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
                        pipeline_raw = typed_doc.get("pipeline")
                        if isinstance(pipeline_raw, list):
                            return _flatten_steps(cast("list[object]", pipeline_raw))
    return []


@router.get("/api/pipeline")
def get_pipeline() -> list[PipelineStepInfo]:
    """Return the pipeline steps in order, flattened from the process definition."""
    return _load_pipeline_steps(get_repo_path())
