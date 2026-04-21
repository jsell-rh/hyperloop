"""Activity API — cycle-by-cycle reconciliation log from FileProbe events."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from dashboard.server.deps import get_repo_path
from dashboard.server.models import (
    ActiveWorker,
    ActivityResponse,
    AdvancePhase,
    CollectPhase,
    CycleDetail,
    CyclePhases,
    IntakePhase,
    PhaseTransition,
    ReapedWorker,
    SpawnedWorker,
    SpawnPhase,
)

router = APIRouter()

_STALE_THRESHOLD_S = 120.0


def _find_events_path(repo_path: Path) -> Path | None:
    """Read the pointer file to find the JSONL events path."""
    pointer = repo_path / ".hyperloop" / ".dashboard-events-path"
    if not pointer.exists():
        return None
    text = pointer.read_text().strip()
    if not text:
        return None
    return Path(text)


def _parse_events(events_path: Path) -> list[dict[str, Any]]:
    """Read and parse JSONL events file, skipping malformed lines."""
    events: list[dict[str, Any]] = []
    try:
        text = events_path.read_text()
    except OSError:
        return events
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _group_by_cycle(
    events: list[dict[str, Any]],
    since_cycle: int | None,
    limit: int,
) -> list[CycleDetail]:
    """Group events by cycle number into CycleDetail objects."""
    cycle_events: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for ev in events:
        cycle = ev.get("cycle")
        if cycle is not None and isinstance(cycle, int):
            cycle_events[cycle].append(ev)

    # Filter by since_cycle
    cycle_nums = sorted(cycle_events.keys(), reverse=True)
    if since_cycle is not None:
        cycle_nums = [c for c in cycle_nums if c > since_cycle]

    # Limit
    cycle_nums = cycle_nums[:limit]

    cycles: list[CycleDetail] = []
    for cycle_num in cycle_nums:
        evts = cycle_events[cycle_num]
        cycles.append(_build_cycle_detail(cycle_num, evts))

    return cycles


def _build_cycle_detail(cycle_num: int, evts: list[dict[str, Any]]) -> CycleDetail:
    """Build a CycleDetail from a list of events for one cycle."""
    # Timestamp: use the first event's timestamp
    timestamp = ""
    duration_s: float | None = None
    for ev in evts:
        if ev.get("event") == "cycle_started":
            timestamp = str(ev.get("ts", ""))
        if ev.get("event") == "cycle_completed":
            duration_s = ev.get("duration_s")

    if not timestamp and evts:
        timestamp = str(evts[0].get("ts", ""))

    # COLLECT: reaped workers
    reaped: list[ReapedWorker] = []
    for ev in evts:
        if ev.get("event") == "worker_reaped":
            reaped.append(
                ReapedWorker(
                    task_id=str(ev.get("task_id", "")),
                    role=str(ev.get("role", "")),
                    verdict=str(ev.get("verdict", "")),
                    duration_s=float(ev.get("duration_s", 0.0)),
                )
            )

    # INTAKE
    intake_ran = False
    created_tasks: int | None = None
    for ev in evts:
        if ev.get("event") == "intake_ran":
            intake_ran = True
            ct = ev.get("created_tasks")
            if ct is not None:
                created_tasks = int(ct)

    # ADVANCE: transitions
    transitions: list[PhaseTransition] = []
    for ev in evts:
        if ev.get("event") == "task_advanced":
            transitions.append(
                PhaseTransition(
                    task_id=str(ev.get("task_id", "")),
                    from_phase=ev.get("from_phase"),
                    to_phase=ev.get("to_phase"),
                )
            )

    # SPAWN: spawned workers
    spawned: list[SpawnedWorker] = []
    for ev in evts:
        if ev.get("event") == "worker_spawned":
            spawned.append(
                SpawnedWorker(
                    task_id=str(ev.get("task_id", "")),
                    role=str(ev.get("role", "")),
                )
            )

    return CycleDetail(
        cycle=cycle_num,
        timestamp=timestamp,
        duration_s=duration_s,
        phases=CyclePhases(
            collect=CollectPhase(reaped=reaped),
            intake=IntakePhase(ran=intake_ran, created_tasks=created_tasks),
            advance=AdvancePhase(transitions=transitions),
            spawn=SpawnPhase(spawned=spawned),
        ),
    )


def _derive_active_workers(events: list[dict[str, Any]]) -> list[ActiveWorker]:
    """Find workers with worker_spawned but no worker_reaped."""
    spawned: dict[str, dict[str, Any]] = {}
    reaped: set[str] = set()

    for ev in events:
        event_type = ev.get("event")
        task_id = str(ev.get("task_id", ""))
        if event_type == "worker_spawned" and task_id:
            spawned[task_id] = ev
        elif event_type == "worker_reaped" and task_id:
            reaped.add(task_id)

    now = datetime.now(UTC)
    active: list[ActiveWorker] = []
    for task_id, ev in spawned.items():
        if task_id not in reaped:
            started_at = str(ev.get("ts", ""))
            duration = 0.0
            if started_at:
                try:
                    started = datetime.fromisoformat(started_at)
                    duration = (now - started).total_seconds()
                except (ValueError, TypeError):
                    pass
            active.append(
                ActiveWorker(
                    task_id=task_id,
                    role=str(ev.get("role", "")),
                    started_at=started_at,
                    duration_s=round(duration, 1),
                )
            )

    return active


def _derive_current_cycle(events: list[dict[str, Any]]) -> int:
    """Get the most recent cycle number from events."""
    max_cycle = 0
    for ev in events:
        cycle = ev.get("cycle")
        if isinstance(cycle, int) and cycle > max_cycle:
            max_cycle = cycle
    return max_cycle


def _derive_status(events: list[dict[str, Any]]) -> str:
    """Derive orchestrator status from events."""
    if not events:
        return "unknown"

    last = events[-1]

    if last.get("event") == "orchestrator_halted":
        return "halted"

    # Check staleness
    ts = last.get("ts")
    if isinstance(ts, str):
        try:
            last_time = datetime.fromisoformat(ts)
            now = datetime.now(UTC)
            if (now - last_time).total_seconds() > _STALE_THRESHOLD_S:
                return "stale"
        except (ValueError, TypeError):
            pass

    return "running"


@router.get("/api/activity")
def get_activity(
    since_cycle: int | None = None,
    limit: int = 20,
) -> ActivityResponse:
    """Return cycle-grouped activity from the FileProbe event log."""
    events_path = _find_events_path(get_repo_path())
    if events_path is None or not events_path.exists():
        return ActivityResponse(
            current_cycle=0,
            orchestrator_status="unknown",
            active_workers=[],
            cycles=[],
            enabled=False,
        )

    events = _parse_events(events_path)
    if not events:
        return ActivityResponse(
            current_cycle=0,
            orchestrator_status="unknown",
            active_workers=[],
            cycles=[],
            enabled=False,
        )

    cycles = _group_by_cycle(events, since_cycle, limit)
    active_workers = _derive_active_workers(events)
    current_cycle = _derive_current_cycle(events)
    status = _derive_status(events)

    return ActivityResponse(
        current_cycle=current_cycle,
        orchestrator_status=status,
        active_workers=active_workers,
        cycles=cycles,
        enabled=True,
    )
