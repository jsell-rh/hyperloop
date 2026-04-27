"""GET /api/agents — per-role agent definitions with layer breakdown and roster."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING, cast

import yaml
from fastapi import APIRouter

from dashboard.server.agents_loader import load_agent_templates
from dashboard.server.deps import get_repo_path
from dashboard.server.models import AgentDefinition, AgentRosterEntry, CheckScript
from dashboard.server.routes._events import find_events_path, parse_events

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


def _compute_roster(repo_path: Path) -> list[AgentRosterEntry]:
    """Compute per-role performance metrics from worker_reaped events."""
    events_path = find_events_path(repo_path)
    if events_path is None or not events_path.exists():
        return []

    events = parse_events(events_path)

    # Group worker_reaped events by role
    per_role: dict[str, list[dict[str, object]]] = defaultdict(list)
    for ev in events:
        if ev.get("event") != "worker_reaped":
            continue
        role = str(ev.get("role", ""))
        if role:
            per_role[role].append(ev)

    roster: list[AgentRosterEntry] = []
    for role in sorted(per_role):
        reaped = per_role[role]
        total = len(reaped)
        pass_count = sum(1 for e in reaped if str(e.get("verdict", "")) == "pass")
        success_rate = pass_count / total if total > 0 else None

        durations: list[float] = []
        for e in reaped:
            dur = e.get("duration_s")
            if dur is not None:
                durations.append(float(str(dur)))
        avg_duration = sum(durations) / len(durations) if durations else None

        # Top 3 failure detail strings
        fail_details: Counter[str] = Counter()
        for e in reaped:
            if str(e.get("verdict", "")) != "pass":
                detail = str(e.get("detail", ""))
                if detail:
                    # Truncate long detail strings
                    truncated = detail[:120] + "..." if len(detail) > 120 else detail
                    fail_details[truncated] += 1
        failure_patterns = [pattern for pattern, _ in fail_details.most_common(3)]

        roster.append(
            AgentRosterEntry(
                role=role,
                success_rate=round(success_rate, 3) if success_rate is not None else None,
                avg_duration_s=round(avg_duration, 1) if avg_duration is not None else None,
                total_executions=total,
                failure_patterns=failure_patterns,
            )
        )

    return roster


@router.get("/api/agents/roster")
def get_agent_roster() -> list[AgentRosterEntry]:
    """Return per-role performance metrics computed from FileProbe events."""
    return _compute_roster(get_repo_path())


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
