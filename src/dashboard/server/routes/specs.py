"""GET /api/specs — spec listing, detail, and drift endpoints."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException

from dashboard.server.deps import get_repo_path, get_spec_source, get_state
from dashboard.server.models import SpecDetail, SpecDriftDetail, SpecSummary, TaskSummary

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
        pr_title=task.pr_title,
        pr_description=task.pr_description,
    )


# ---------------------------------------------------------------------------
# Summary loading helpers
# ---------------------------------------------------------------------------


def _load_summaries_from_state() -> dict[str, dict[str, object]]:
    """Load and parse summary records from the state store.

    Returns a dict of {spec_path: parsed_yaml_dict}.
    """
    state = get_state()
    raw = state.list_summaries()
    result: dict[str, dict[str, object]] = {}
    for spec_path, content in raw.items():
        parsed = yaml.safe_load(content)
        if isinstance(parsed, dict):
            result[spec_path] = parsed
    return result


# ---------------------------------------------------------------------------
# Audit event helpers
# ---------------------------------------------------------------------------


def _find_events_path(repo_path: Path) -> Path | None:
    """Find the JSONL events file in the cache directory."""
    import hashlib

    repo_hash = hashlib.md5(str(repo_path).encode()).hexdigest()[:8]
    events_path = Path.home() / ".cache" / "hyperloop" / repo_hash / "events.jsonl"
    if events_path.exists():
        return events_path

    pointer = repo_path / ".hyperloop" / ".dashboard-events-path"
    if pointer.exists():
        text = pointer.read_text().strip()
        if text:
            return Path(text)

    return None


def _load_audit_events(repo_path: Path) -> dict[str, dict[str, str]]:
    """Load the latest audit result per spec from FileProbe events.

    Returns {spec_path: {"result": "aligned"|"misaligned", "ts": "..."}}.
    """
    events_path = _find_events_path(repo_path)
    if events_path is None or not events_path.exists():
        return {}

    try:
        text = events_path.read_text()
    except OSError:
        return {}

    latest: dict[str, dict[str, str]] = {}
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event") != "audit_ran":
            continue
        spec_ref_raw = str(ev.get("spec_ref", ""))
        spec_path = spec_ref_raw.split("@")[0]
        result = str(ev.get("result", ""))
        ts = str(ev.get("ts", ""))
        if spec_path and result:
            latest[spec_path] = {"result": result, "ts": ts}

    return latest


# ---------------------------------------------------------------------------
# Stage computation
# ---------------------------------------------------------------------------


def compute_spec_stage(
    *,
    spec_path: str,
    statuses: list[str],
    has_summary: bool,
    audit_result: str | None,
    current_sha: str | None,
    pinned_sha: str | None,
) -> tuple[str, str | None, str]:
    """Derive lifecycle stage, drift_type, and drift_detail for a spec.

    Returns (stage, drift_type, drift_detail).
    """
    # Freshness drift takes priority when SHAs differ
    if current_sha is not None and pinned_sha is not None and current_sha != pinned_sha:
        return (
            "freshness-drift",
            "freshness",
            f"spec changed: pinned {pinned_sha[:8]} but current is {current_sha[:8]}",
        )

    # Baselined: summary exists but no tasks
    if has_summary and len(statuses) == 0:
        return ("baselined", None, "")

    # Coverage gap: no tasks and no summary
    if len(statuses) == 0 and not has_summary:
        return ("written", "coverage", f"no tasks cover {spec_path}")

    # All tasks failed
    if statuses and all(s == "failed" for s in statuses):
        return ("failed", None, "all tasks failed")

    # Any task in-progress or not-started with other active work
    if "in-progress" in statuses:
        return ("in-progress", None, "")

    # All tasks completed
    all_completed = all(s == "completed" for s in statuses) and len(statuses) > 0
    if all_completed:
        if audit_result == "aligned":
            return ("converged", None, "")
        if audit_result == "misaligned":
            return ("alignment-gap", "alignment", "auditor found misalignment")
        return ("pending-audit", None, "")

    # Mixed terminal + not-started (some work happening)
    return ("in-progress", None, "")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/specs")
def list_specs() -> list[SpecSummary]:
    """List all specs with task progress summary, drift info, and lifecycle stage.

    Finds spec files via StateStore.list_files, reads content via SpecSource
    for titles, and groups tasks by unversioned spec_ref. Computes lifecycle
    stage and drift detection per spec.
    """
    state = get_state()
    spec_source = get_spec_source()
    repo_path = get_repo_path()

    # Get all tasks and group by unversioned spec_ref
    world = state.get_world()

    # Collect statuses and pinned SHAs per spec path
    spec_statuses: dict[str, list[str]] = {}
    spec_pinned_shas: dict[str, set[str]] = {}
    for task in world.tasks.values():
        base_ref = task.spec_ref.split("@")[0]
        spec_statuses.setdefault(base_ref, []).append(_status_str(task.status))
        # Extract pinned SHA from spec_ref
        parts = task.spec_ref.split("@")
        if len(parts) >= 2:
            spec_pinned_shas.setdefault(base_ref, set()).add(parts[1])

    # Load summaries and audit events
    summaries = _load_summaries_from_state()
    audit_events = _load_audit_events(repo_path)

    # Find all spec files
    spec_files = state.list_files("specs/*.md")

    results: list[SpecSummary] = []
    seen_specs: set[str] = set()

    for spec_path in spec_files:
        seen_specs.add(spec_path)
        content = spec_source.read(spec_path)
        title = _extract_title(content)
        statuses = spec_statuses.get(spec_path, [])

        # Get current file SHA
        current_sha: str | None = spec_source.file_version(spec_path) or None

        # Get pinned SHA (use first if multiple), normalize commit→blob
        pinned_shas = spec_pinned_shas.get(spec_path)
        pinned_sha: str | None = None
        if pinned_shas:
            raw_sha = sorted(pinned_shas)[0]
            pinned_sha = spec_source.file_version_at(spec_path, raw_sha)

        # Get audit info
        audit_info = audit_events.get(spec_path)
        audit_result = audit_info["result"] if audit_info else None
        audit_ts = audit_info["ts"] if audit_info else None

        # Check summary for audit info fallback
        summary_data = summaries.get(spec_path)
        has_summary = summary_data is not None
        if summary_data is not None and audit_result is None:
            raw_result = summary_data.get("last_audit_result")
            if raw_result is not None:
                audit_result = str(raw_result)
            raw_ts = summary_data.get("last_audit")
            if raw_ts is not None and audit_ts is None:
                audit_ts = str(raw_ts)

        stage, drift_type, drift_detail = compute_spec_stage(
            spec_path=spec_path,
            statuses=statuses,
            has_summary=has_summary,
            audit_result=audit_result,
            current_sha=current_sha,
            pinned_sha=pinned_sha,
        )

        results.append(
            SpecSummary(
                spec_ref=spec_path,
                title=title,
                tasks_total=len(statuses),
                tasks_complete=statuses.count("completed"),
                tasks_in_progress=statuses.count("in-progress"),
                tasks_failed=statuses.count("failed"),
                tasks_not_started=statuses.count("not-started"),
                drift_type=drift_type,
                drift_detail=drift_detail,
                stage=stage,
                last_audit_result=audit_result,
                last_audit=audit_ts,
                current_sha=current_sha,
                pinned_sha=pinned_sha,
            )
        )

    # Include specs that have tasks but no spec file on disk
    for spec_ref, statuses in spec_statuses.items():
        if spec_ref in seen_specs:
            continue
        content = spec_source.read(spec_ref)
        title = _extract_title(content) if content else "(untitled)"

        current_sha = spec_source.file_version(spec_ref) or None
        pinned_shas = spec_pinned_shas.get(spec_ref)
        pinned_sha = sorted(pinned_shas)[0] if pinned_shas else None

        audit_info = audit_events.get(spec_ref)
        audit_result = audit_info["result"] if audit_info else None
        audit_ts = audit_info["ts"] if audit_info else None

        summary_data = summaries.get(spec_ref)
        has_summary = summary_data is not None
        if summary_data is not None and audit_result is None:
            raw_result = summary_data.get("last_audit_result")
            if raw_result is not None:
                audit_result = str(raw_result)
            raw_ts = summary_data.get("last_audit")
            if raw_ts is not None and audit_ts is None:
                audit_ts = str(raw_ts)

        stage, drift_type, drift_detail = compute_spec_stage(
            spec_path=spec_ref,
            statuses=statuses,
            has_summary=has_summary,
            audit_result=audit_result,
            current_sha=current_sha,
            pinned_sha=pinned_sha,
        )

        results.append(
            SpecSummary(
                spec_ref=spec_ref,
                title=title,
                tasks_total=len(statuses),
                tasks_complete=statuses.count("completed"),
                tasks_in_progress=statuses.count("in-progress"),
                tasks_failed=statuses.count("failed"),
                tasks_not_started=statuses.count("not-started"),
                drift_type=drift_type,
                drift_detail=drift_detail,
                stage=stage,
                last_audit_result=audit_result,
                last_audit=audit_ts,
                current_sha=current_sha,
                pinned_sha=pinned_sha,
            )
        )

    return results


@router.get("/api/specs/{spec_ref:path}/drift")
def get_spec_drift(spec_ref: str) -> SpecDriftDetail:
    """Return detailed drift info for a single spec, including old/new content."""
    # Strip trailing /drift if FastAPI captured it as part of spec_ref
    if spec_ref.endswith("/drift"):
        spec_ref = spec_ref[: -len("/drift")]

    spec_source = get_spec_source()
    state = get_state()
    repo_path = get_repo_path()

    # Read current content
    current_content = spec_source.read(spec_ref)
    if not current_content:
        raise HTTPException(status_code=404, detail=f"Spec {spec_ref} not found")

    current_sha = spec_source.file_version(spec_ref) or None

    # Find pinned SHA from tasks
    world = state.get_world()
    pinned_shas: set[str] = set()
    for task in world.tasks.values():
        base = task.spec_ref.split("@")[0]
        if base == spec_ref:
            parts = task.spec_ref.split("@")
            if len(parts) >= 2:
                pinned_shas.add(parts[1])

    # If no task pins, check summaries
    if not pinned_shas:
        summaries = _load_summaries_from_state()
        summary_data = summaries.get(spec_ref)
        if summary_data is not None:
            raw_ref = summary_data.get("spec_ref")
            if raw_ref is not None:
                parts = str(raw_ref).split("@")
                if len(parts) >= 2:
                    pinned_shas.add(parts[1])

    pinned_sha = sorted(pinned_shas)[0] if pinned_shas else None

    # Determine drift type
    audit_events = _load_audit_events(repo_path)
    audit_info = audit_events.get(spec_ref)

    statuses: list[str] = []
    for task in world.tasks.values():
        if task.spec_ref.split("@")[0] == spec_ref:
            statuses.append(_status_str(task.status))

    summaries = _load_summaries_from_state()
    has_summary = spec_ref in summaries
    audit_result = audit_info["result"] if audit_info else None
    if has_summary and audit_result is None:
        raw_r = summaries[spec_ref].get("last_audit_result")
        if raw_r is not None:
            audit_result = str(raw_r)

    _stage, drift_type, drift_detail = compute_spec_stage(
        spec_path=spec_ref,
        statuses=statuses,
        has_summary=has_summary,
        audit_result=audit_result,
        current_sha=current_sha,
        pinned_sha=pinned_sha,
    )

    # For freshness drift, try to read old content using blob SHA
    old_content: str | None = None
    if drift_type == "freshness" and pinned_sha is not None:
        # Read old content via git show <blob_sha> (blob SHA, not commit:path)
        result = subprocess.run(
            ["git", "-C", str(repo_path), "show", pinned_sha],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            old_content = result.stdout

    return SpecDriftDetail(
        spec_ref=spec_ref,
        drift_type=drift_type,
        drift_detail=drift_detail,
        old_sha=pinned_sha,
        new_sha=current_sha,
        old_content=old_content,
        new_content=current_content if drift_type == "freshness" else None,
    )


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
