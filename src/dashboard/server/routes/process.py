"""GET /api/process — phase map, gates, actions, hooks, and process learning."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import yaml
from fastapi import APIRouter

if TYPE_CHECKING:
    from pathlib import Path

from dashboard.server.deps import get_repo_path
from dashboard.server.models import (
    PhaseDefinition,
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


def _parse_phase_map(
    process_data: dict[str, object],
) -> tuple[dict[str, PhaseDefinition], list[str]]:
    """Extract the flat phase map from a process definition.

    Supports both the new flat ``phases:`` key and the legacy ``pipeline:``
    key.  For legacy pipeline definitions the phases are synthesised from
    the ordered step list.

    Returns (phase_dict, ordered_phase_names).
    """
    # --- New format: explicit ``phases`` dict ---
    phases_raw = process_data.get("phases")
    if isinstance(phases_raw, dict):
        phase_dict: dict[str, PhaseDefinition] = {}
        for name, cfg in cast("dict[str, object]", phases_raw).items():
            if isinstance(cfg, dict):
                typed_cfg = cast("dict[str, str]", cfg)
                phase_dict[name] = PhaseDefinition(
                    run=typed_cfg.get("run", name),
                    on_pass=typed_cfg.get("on_pass", "done"),
                    on_fail=typed_cfg.get("on_fail", "done"),
                    on_wait=typed_cfg.get("on_wait"),
                )
        # Preserve insertion order from YAML (Python 3.7+ dicts are ordered)
        return phase_dict, list(phase_dict.keys())

    # --- Legacy format: ``pipeline`` list ---
    pipeline_raw = process_data.get("pipeline")
    if isinstance(pipeline_raw, list):
        return _synthesise_phases_from_pipeline(
            cast("list[object]", pipeline_raw),
        )

    return {}, []


def _synthesise_phases_from_pipeline(
    steps: list[object],
) -> tuple[dict[str, PhaseDefinition], list[str]]:
    """Walk a legacy pipeline list and build a flat phase map.

    Loop steps are flattened — each child appears in order. The on_fail
    of the last step inside a loop points back to the first step of
    that loop to represent the retry semantics.
    """
    flat_names: list[str] = []
    flat_types: list[str] = []

    # Track loop boundaries for on_fail back-arrows
    loop_first_index: int | None = None

    for raw_step in steps:
        if not isinstance(raw_step, dict):
            continue
        step = cast("dict[str, object]", raw_step)
        if "loop" in step:
            children = step["loop"]
            if isinstance(children, list):
                loop_start = len(flat_names)
                for child in cast("list[object]", children):
                    if not isinstance(child, dict):
                        continue
                    child_step = cast("dict[str, object]", child)
                    name, stype = _extract_step_name_type(child_step)
                    if name:
                        flat_names.append(name)
                        flat_types.append(stype)
                # Mark the loop boundary
                if len(flat_names) > loop_start:
                    loop_first_index = loop_start
        else:
            name, stype = _extract_step_name_type(step)
            if name:
                flat_names.append(name)
                flat_types.append(stype)

    # Build phase definitions with forward on_pass and loop-aware on_fail
    phase_dict: dict[str, PhaseDefinition] = {}
    for i, name in enumerate(flat_names):
        on_pass = flat_names[i + 1] if i + 1 < len(flat_names) else "done"
        # If this step is the last in a loop, on_fail points to loop start
        on_fail = "done"
        if loop_first_index is not None and i >= loop_first_index:
            on_fail = flat_names[loop_first_index]
        phase_dict[name] = PhaseDefinition(
            run=f"{flat_types[i]}:{name}" if flat_types[i] != "agent" else name,
            on_pass=on_pass,
            on_fail=on_fail,
        )

    return phase_dict, flat_names


def _extract_step_name_type(step: dict[str, object]) -> tuple[str | None, str]:
    """Return (name, type) for a single pipeline step dict."""
    for key in ("agent", "gate", "check", "action"):
        if key in step:
            return str(step[key]), key
    return None, ""


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
def get_process(repo: str | None = None) -> ProcessResponse:
    """Return the full process definition with learning state."""
    repo_path = get_repo_path()

    process_yaml = _find_and_read_process_yaml(repo_path)

    # Parse phase map (supports both new and legacy formats)
    phases, phase_order = _parse_phase_map(process_yaml)

    # Raw YAML for display
    pipeline_raw_list = process_yaml.get("phases") or process_yaml.get("pipeline", [])
    pipeline_raw = yaml.dump(
        pipeline_raw_list if isinstance(pipeline_raw_list, (list, dict)) else [],
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
        phases=phases,
        phase_order=phase_order,
        pipeline_raw=pipeline_raw,
        gates=gates,
        actions=actions,
        hooks=hooks,
        process_learning=process_learning,
        source_file=source_file,
        base_ref=kustomization.get("base_ref"),
    )
