"""GET /api/fleet — fleet overview of all hyperloop instances."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from dashboard.server.models import FleetResponse, InstanceSummary
from dashboard.server.routes._events import discover_instances, parse_events_tail

router = APIRouter()

_RUNNING_THRESHOLD_S = 300.0  # 5 minutes
_IDLE_THRESHOLD_S = 3600.0  # 60 minutes


def _compute_instance_summary(
    repo_hash: str,
    repo_name: str,
    repo_path: str,
    events: list[dict[str, Any]],
) -> InstanceSummary:
    """Compute summary KPIs for a single hyperloop instance."""
    if not events:
        return InstanceSummary(
            repo_hash=repo_hash,
            repo_name=repo_name,
            repo_path=repo_path,
            status="empty",
            last_event_at=None,
            current_cycle=0,
            active_workers=0,
            specs_converged=0,
            specs_total=0,
            drift_remaining=0,
            rounds_completed=0,
            verify_pass_rate=0.0,
        )

    # Trim to latest orchestrator session
    last_start_idx = 0
    for i, ev in enumerate(events):
        if ev.get("event") == "orchestrator_started":
            last_start_idx = i
    if last_start_idx > 0:
        events = events[last_start_idx:]

    # Last event timestamp + status
    last_ts: str | None = None
    for ev in reversed(events):
        ts = ev.get("ts")
        if isinstance(ts, str) and ts:
            last_ts = ts
            break

    status = "empty"
    if last_ts:
        try:
            last_dt = datetime.fromisoformat(last_ts)
            elapsed = (datetime.now(UTC) - last_dt).total_seconds()
            if elapsed < _RUNNING_THRESHOLD_S:
                status = "running"
            elif elapsed < _IDLE_THRESHOLD_S:
                status = "idle"
            else:
                status = "stale"
        except (ValueError, TypeError):
            status = "stale"

    # Current cycle
    max_cycle = 0
    for ev in events:
        cycle = ev.get("cycle")
        if isinstance(cycle, int) and cycle > max_cycle:
            max_cycle = cycle

    # Active workers (spawned but not reaped)
    worker_state: dict[str, bool] = {}
    for ev in events:
        event_type = ev.get("event")
        task_id = str(ev.get("task_id", ""))
        if event_type == "worker_spawned" and task_id:
            worker_state[task_id] = True
        elif event_type == "worker_reaped" and task_id:
            worker_state[task_id] = False
    active_workers = sum(1 for v in worker_state.values() if v)

    # Specs converged + total from latest reconcile_completed
    drift_remaining = 0
    specs_total = 0
    for ev in reversed(events):
        if ev.get("event") == "reconcile_completed":
            dc = ev.get("drift_count")
            if isinstance(dc, int):
                drift_remaining = dc
            ts_val = ev.get("total_specs")
            if isinstance(ts_val, int):
                specs_total = ts_val
            break

    # Fallback: count unique spec_refs from audit events
    if specs_total == 0:
        spec_refs: set[str] = set()
        for ev in events:
            if ev.get("event") == "audit_ran":
                sr = ev.get("spec_ref")
                if isinstance(sr, str) and sr:
                    spec_refs.add(sr)
        specs_total = len(spec_refs)

    # Count convergence_marked events
    converged_specs: set[str] = set()
    for ev in events:
        if ev.get("event") == "convergence_marked":
            sp = ev.get("spec_ref") or ev.get("spec_path")
            if isinstance(sp, str) and sp:
                converged_specs.add(sp)
    if converged_specs:
        specs_converged = len(converged_specs)
    else:
        specs_converged = max(0, specs_total - drift_remaining)

    # Rounds completed (worker_reaped count)
    rounds_completed = sum(1 for ev in events if ev.get("event") == "worker_reaped")

    # Verify pass rate
    verify_pass = 0
    verify_total = 0
    for ev in events:
        if ev.get("event") == "worker_reaped":
            role = str(ev.get("role", ""))
            if role == "verifier":
                verify_total += 1
                if ev.get("verdict") == "pass":
                    verify_pass += 1

    verify_pass_rate = 0.0
    if verify_total > 0:
        verify_pass_rate = round(verify_pass / verify_total * 100, 1)

    return InstanceSummary(
        repo_hash=repo_hash,
        repo_name=repo_name,
        repo_path=repo_path,
        status=status,
        last_event_at=last_ts,
        current_cycle=max_cycle,
        active_workers=active_workers,
        specs_converged=specs_converged,
        specs_total=specs_total,
        drift_remaining=drift_remaining,
        rounds_completed=rounds_completed,
        verify_pass_rate=verify_pass_rate,
    )


@router.get("/api/fleet")
def list_instances() -> FleetResponse:
    """Discover all hyperloop instances and return summary KPIs for each."""
    instances = discover_instances()

    summaries: list[InstanceSummary] = []
    for repo_hash, repo_path, events_path in instances:
        repo_name = repo_path.name
        events = parse_events_tail(events_path, max_lines=500)
        summary = _compute_instance_summary(
            repo_hash=repo_hash,
            repo_name=repo_name,
            repo_path=str(repo_path),
            events=events,
        )
        summaries.append(summary)

    # Sort by most recently active first
    def _sort_key(inst: InstanceSummary) -> str:
        return inst.last_event_at or ""

    summaries.sort(key=_sort_key, reverse=True)

    return FleetResponse(instances=summaries)
