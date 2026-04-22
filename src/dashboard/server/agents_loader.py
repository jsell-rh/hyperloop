"""Shared agent template loading — used by both tasks and agents routes."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, cast

import yaml

if TYPE_CHECKING:
    from pathlib import Path


def _extract_agent(raw: object) -> tuple[str, dict[str, str]] | None:
    """Extract agent name and template from a raw YAML document.

    Returns (name, {"prompt": ..., "guidelines": ...}) or None if not an Agent doc.
    """
    if not isinstance(raw, dict):
        return None
    doc = cast("dict[str, object]", raw)
    if doc.get("kind") != "Agent":
        return None
    metadata = doc.get("metadata")
    name = ""
    if isinstance(metadata, dict):
        meta = cast("dict[str, object]", metadata)
        name = str(meta.get("name", ""))
    if not name:
        name = str(doc.get("name", ""))
    if not name:
        return None
    return name, {
        "prompt": str(doc.get("prompt", "")),
        "guidelines": str(doc.get("guidelines", "")).strip(),
    }


def load_agent_templates(repo_path: Path) -> dict[str, dict[str, str]]:
    """Load agent templates via kustomize build, falling back to raw YAML files.

    Tries kustomize build first (resolves remote refs), then falls back to
    reading local YAML files directly.

    Returns a dict mapping agent name to {"prompt": ..., "guidelines": ...}.
    """
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
            for raw_doc in yaml.safe_load_all(result.stdout):
                extracted = _extract_agent(raw_doc)
                if extracted is None:
                    continue
                name, tmpl = extracted
                templates[name] = tmpl
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
                raw_doc = yaml.safe_load(f)
        except (yaml.YAMLError, OSError):
            continue
        extracted = _extract_agent(raw_doc)
        if extracted is None:
            continue
        name, tmpl = extracted
        templates[name] = tmpl
    return templates
