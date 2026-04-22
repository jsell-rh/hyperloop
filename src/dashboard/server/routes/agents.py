"""GET /api/agents — per-role agent definitions with layer breakdown."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import yaml
from fastapi import APIRouter

from dashboard.server.agents_loader import load_agent_templates
from dashboard.server.deps import get_repo_path
from dashboard.server.models import AgentDefinition, CheckScript

if TYPE_CHECKING:
    from pathlib import Path

router = APIRouter()


def _read_process_overlays(repo_path: Path) -> dict[str, dict[str, str]]:
    """Read .hyperloop/agents/process/*-overlay.yaml files.

    Returns a dict mapping agent name to {"guidelines": ..., "file": ...}.
    """
    overlay_dir = repo_path / ".hyperloop" / "agents" / "process"
    overlays: dict[str, dict[str, str]] = {}

    if not overlay_dir.is_dir():
        return overlays

    for f in sorted(overlay_dir.glob("*-overlay.yaml")):
        try:
            doc = yaml.safe_load(f.read_text())
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(doc, dict):
            continue
        typed_doc = cast("dict[str, object]", doc)
        metadata = typed_doc.get("metadata")
        name = ""
        if isinstance(metadata, dict):
            meta = cast("dict[str, object]", metadata)
            name = str(meta.get("name", ""))
        if not name:
            # Fall back to deriving name from filename
            name = f.stem.replace("-overlay", "")
        guidelines = typed_doc.get("guidelines", "")
        if name and isinstance(guidelines, str) and guidelines.strip():
            overlays[name] = {
                "guidelines": guidelines.strip(),
                "file": str(f.relative_to(repo_path)),
            }

    return overlays


@router.get("/api/agents")
def list_agents() -> list[AgentDefinition]:
    """Return per-role agent definitions with layer breakdown."""
    repo_path = get_repo_path()
    templates = load_agent_templates(repo_path)
    process_overlays = _read_process_overlays(repo_path)

    results: list[AgentDefinition] = []
    for name, tmpl in sorted(templates.items()):
        overlay = process_overlays.get(name)
        results.append(
            AgentDefinition(
                name=name,
                prompt=tmpl["prompt"],
                guidelines=tmpl["guidelines"],
                has_process_patches=overlay is not None,
                process_overlay_guidelines=overlay["guidelines"] if overlay else None,
                process_overlay_file=overlay["file"] if overlay else None,
            )
        )
    return results


@router.get("/api/agents/checks")
def list_checks() -> list[CheckScript]:
    """Return check scripts from .hyperloop/checks/."""
    repo_path = get_repo_path()
    checks_dir = repo_path / ".hyperloop" / "checks"

    if not checks_dir.is_dir():
        return []

    results: list[CheckScript] = []
    for script in sorted(checks_dir.glob("*.sh")):
        try:
            content = script.read_text()
        except OSError:
            continue
        results.append(
            CheckScript(
                name=script.name,
                path=str(script.relative_to(repo_path)),
                content=content,
            )
        )
    return results
