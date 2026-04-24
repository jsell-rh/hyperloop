"""Reconciler domain logic — pure drift detection, GC planning, and convergence.

All functions are pure: they take immutable inputs and return results.
No I/O, no port calls, no framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hyperloop.domain.model import DriftType, PMFailureResponse, Task, TaskStatus

# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

_TERMINAL_STATUSES = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED})
_ACTIVE_STATUSES = frozenset({TaskStatus.NOT_STARTED, TaskStatus.IN_PROGRESS})

PhaseMap = dict[str, object]
"""Flat mapping of phase name to step definition (phase map from process config)."""


@dataclass(frozen=True)
class DriftResult:
    """A detected drift between spec (desired state) and code (actual state)."""

    spec_path: str
    drift_type: DriftType
    detail: str


@dataclass(frozen=True)
class GCAction:
    """A terminal task eligible for garbage collection."""

    task_id: str
    spec_ref: str


@dataclass(frozen=True)
class TaskRetirement:
    """A task to retire because its spec was deleted."""

    task_id: str
    reason: str


@dataclass(frozen=True)
class OrphanedPhase:
    """An in-progress task whose phase is missing from the current phase map."""

    task_id: str
    phase: str


@dataclass(frozen=True)
class Summary:
    """Archived summary of completed work for a spec."""

    spec_path: str
    spec_ref: str
    total_tasks: int
    completed: int
    failed: int
    failure_themes: list[str] = field(default_factory=list)
    last_audit: str | None = None
    last_audit_result: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_spec_path(spec_ref: str) -> str:
    """Extract the spec path from a spec_ref like 'specs/auth.md@abc123'."""
    return spec_ref.split("@")[0]


def _extract_sha(spec_ref: str) -> str | None:
    """Extract the SHA from a spec_ref like 'specs/auth.md@abc123'."""
    parts = spec_ref.split("@")
    if len(parts) >= 2:
        return parts[1]
    return None


# ---------------------------------------------------------------------------
# Coverage detection
# ---------------------------------------------------------------------------


def detect_coverage_gaps(
    tasks: dict[str, Task],
    spec_paths: list[str],
    summaries: dict[str, Summary],
) -> list[DriftResult]:
    """Find specs with no tasks and no summary (coverage tier).

    A spec is covered if any task has a spec_ref starting with that path,
    or if a summary exists with a matching key.
    """
    results: list[DriftResult] = []
    for spec_path in spec_paths:
        has_task = any(task.spec_ref.startswith(spec_path) for task in tasks.values())
        has_summary = spec_path in summaries
        if not has_task and not has_summary:
            results.append(
                DriftResult(
                    spec_path=spec_path,
                    drift_type=DriftType.COVERAGE,
                    detail=f"no tasks or summaries cover {spec_path}",
                )
            )
    return results


# ---------------------------------------------------------------------------
# Freshness detection
# ---------------------------------------------------------------------------


def detect_freshness_drift(
    tasks: dict[str, Task],
    spec_versions: dict[str, str],
    summaries: dict[str, Summary] | None = None,
) -> list[DriftResult]:
    """Find specs where task or summary SHA differs from current HEAD SHA.

    Groups tasks by spec path, then compares pinned SHA against current version.
    Also checks summaries for stale SHAs when no tasks exist for a spec.
    """
    spec_shas: dict[str, set[str]] = {}
    for task in tasks.values():
        path = _extract_spec_path(task.spec_ref)
        sha = _extract_sha(task.spec_ref)
        if sha is not None:
            spec_shas.setdefault(path, set()).add(sha)

    # Include summary SHAs for specs with no active tasks
    if summaries is not None:
        for spec_path, summary in summaries.items():
            if spec_path not in spec_shas:
                summary_sha = _extract_sha(summary.spec_ref)
                if summary_sha is not None:
                    spec_shas.setdefault(spec_path, set()).add(summary_sha)

    results: list[DriftResult] = []
    for spec_path, current_sha in spec_versions.items():
        pinned = spec_shas.get(spec_path)
        if pinned is not None and current_sha not in pinned:
            old_shas = ", ".join(sorted(pinned))
            results.append(
                DriftResult(
                    spec_path=spec_path,
                    drift_type=DriftType.FRESHNESS,
                    detail=f"pinned {old_shas} but HEAD is {current_sha}",
                )
            )
    return results


# ---------------------------------------------------------------------------
# Convergence check
# ---------------------------------------------------------------------------


def check_convergence_needed(
    tasks: dict[str, Task],
    converged_specs: set[str],
) -> list[str]:
    """Find spec_refs where all tasks are completed but not yet converged.

    Returns a list of spec_refs that need an alignment audit.
    """
    spec_tasks: dict[str, list[Task]] = {}
    for task in tasks.values():
        spec_tasks.setdefault(task.spec_ref, []).append(task)

    results: list[str] = []
    for spec_ref, group in spec_tasks.items():
        if spec_ref in converged_specs:
            continue
        all_completed = all(t.status == TaskStatus.COMPLETED for t in group)
        if all_completed:
            results.append(spec_ref)
    return results


# ---------------------------------------------------------------------------
# Garbage collection planning
# ---------------------------------------------------------------------------


def plan_gc(
    tasks: dict[str, Task],
    retention_days: int,
    task_ages: dict[str, float],
) -> list[GCAction]:
    """Find terminal tasks past the retention period.

    Args:
        tasks: current task map
        retention_days: how many days terminal tasks are kept
        task_ages: mapping of task_id to age in days
    """
    results: list[GCAction] = []
    for task_id, task in tasks.items():
        if task.status not in _TERMINAL_STATUSES:
            continue
        age = task_ages.get(task_id, 0.0)
        if age > retention_days:
            results.append(GCAction(task_id=task_id, spec_ref=task.spec_ref))
    return results


# ---------------------------------------------------------------------------
# Deleted spec handling
# ---------------------------------------------------------------------------


def handle_deleted_specs(
    tasks: dict[str, Task],
    current_spec_paths: set[str],
) -> list[TaskRetirement]:
    """Find in-progress tasks whose spec has been deleted.

    Completed and failed tasks are eligible for normal GC, not immediate retirement.
    """
    results: list[TaskRetirement] = []
    for task in tasks.values():
        if task.status in _TERMINAL_STATUSES:
            continue
        spec_path = _extract_spec_path(task.spec_ref)
        if spec_path not in current_spec_paths:
            results.append(TaskRetirement(task_id=task.id, reason="spec deleted"))
    return results


# ---------------------------------------------------------------------------
# PM failure handling
# ---------------------------------------------------------------------------


def handle_pm_failure(consecutive_failures: int, max_failures: int) -> PMFailureResponse:
    """Decide PM failure response: 'backoff' or 'halt'."""
    if consecutive_failures >= max_failures:
        return PMFailureResponse.HALT
    return PMFailureResponse.BACKOFF


# ---------------------------------------------------------------------------
# Phase orphan detection
# ---------------------------------------------------------------------------


def detect_phase_orphans(
    tasks: dict[str, Task],
    phase_map: PhaseMap,
) -> list[OrphanedPhase]:
    """Find in-progress tasks whose phase is not in the current phase map."""
    results: list[OrphanedPhase] = []
    for task in tasks.values():
        if task.status in _TERMINAL_STATUSES:
            continue
        if task.phase is None:
            continue
        if task.phase not in phase_map:
            results.append(OrphanedPhase(task_id=task.id, phase=task.phase))
    return results


# ---------------------------------------------------------------------------
# Summary coverage check
# ---------------------------------------------------------------------------


def summary_covers_spec(
    spec_path: str,
    current_sha: str,
    summaries: dict[str, Summary],
) -> bool:
    """Check if a summary exists for spec_path with a matching SHA."""
    summary = summaries.get(spec_path)
    if summary is None:
        return False
    summary_sha = _extract_sha(summary.spec_ref)
    return summary_sha == current_sha
