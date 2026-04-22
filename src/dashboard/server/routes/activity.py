"""Activity API — cycle-by-cycle reconciliation log from FileProbe events."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from dashboard.server.deps import get_repo_path, get_state
from dashboard.server.models import (
    ActiveWorker,
    ActivityResponse,
    AdvancePhase,
    CollectPhase,
    CycleDetail,
    CyclePhases,
    FlatEvent,
    IntakePhase,
    PhaseTransition,
    ReapedWorker,
    SpawnedWorker,
    SpawnPhase,
    TaskInFlight,
    WorkerHistoryEntry,
)

router = APIRouter()

_STALE_THRESHOLD_S = 120.0


def _find_events_path(repo_path: Path) -> Path | None:
    """Find the JSONL events file in the cache directory."""
    import hashlib

    repo_hash = hashlib.md5(str(repo_path).encode()).hexdigest()[:8]
    events_path = Path.home() / ".cache" / "hyperloop" / repo_hash / "events.jsonl"
    if events_path.exists():
        return events_path

    # Legacy: check pointer file in repo (older versions wrote it there)
    pointer = repo_path / ".hyperloop" / ".dashboard-events-path"
    if pointer.exists():
        text = pointer.read_text().strip()
        if text:
            return Path(text)

    return None


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
    """Find workers with worker_spawned but no subsequent worker_reaped.

    Processes events in chronological order so that a respawn after a reap
    correctly marks the worker as active again.
    """
    # Track the latest state per task_id: either a spawn event or None (reaped)
    latest: dict[str, dict[str, Any] | None] = {}

    for ev in events:
        event_type = ev.get("event")
        task_id = str(ev.get("task_id", ""))
        if event_type == "worker_spawned" and task_id:
            latest[task_id] = ev
        elif event_type == "worker_reaped" and task_id:
            latest[task_id] = None

    now = datetime.now(UTC)
    active: list[ActiveWorker] = []
    for task_id, ev in latest.items():
        if ev is not None:
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


def _build_tasks_in_flight(
    events: list[dict[str, Any]],
    active_workers: list[ActiveWorker],
) -> list[TaskInFlight]:
    """Build in-flight task cards from state store and event log."""
    try:
        state = get_state()
        world = state.get_world()
    except Exception:
        return []

    active_by_task: dict[str, ActiveWorker] = {w.task_id: w for w in active_workers}

    in_flight: list[TaskInFlight] = []
    for task in world.tasks.values():
        if task.status.value not in ("in_progress",):
            continue

        # Build worker history from events
        history: list[WorkerHistoryEntry] = []
        for ev in events:
            if ev.get("event") == "worker_reaped" and ev.get("task_id") == task.id:
                history.append(
                    WorkerHistoryEntry(
                        role=str(ev.get("role", "")),
                        round=int(ev.get("round", 0)),
                        started_at=str(ev.get("ts", "")),
                        duration_s=float(ev.get("duration_s", 0.0)),
                        verdict=ev.get("verdict"),
                    )
                )

        # Strip @version from spec_ref for display
        spec_ref = task.spec_ref.split("@")[0] if "@" in task.spec_ref else task.spec_ref

        in_flight.append(
            TaskInFlight(
                task_id=task.id,
                title=task.title,
                status="in-progress",
                phase=str(task.phase) if task.phase is not None else None,
                round=task.round,
                spec_ref=spec_ref,
                current_worker=active_by_task.get(task.id),
                worker_history=history,
            )
        )

    # Sort by task ID for stable ordering
    in_flight.sort(key=lambda t: t.task_id)
    return in_flight


def _build_flattened_events(events: list[dict[str, Any]]) -> list[FlatEvent]:
    """Extract non-empty events from raw events into a flat list."""
    flat: list[FlatEvent] = []

    for ev in events:
        event_type = ev.get("event", "")
        ts = str(ev.get("ts", ""))
        cycle = int(ev.get("cycle", 0))
        task_id = ev.get("task_id")
        if isinstance(task_id, str) and task_id:
            pass
        else:
            task_id = None

        if event_type == "worker_spawned":
            role = ev.get("role", "")
            flat.append(
                FlatEvent(
                    timestamp=ts,
                    cycle=cycle,
                    event_type="worker_spawned",
                    task_id=task_id,
                    detail=f"Spawned {role} for {task_id}",
                    verdict=None,
                    duration_s=None,
                )
            )
        elif event_type == "worker_reaped":
            role = ev.get("role", "")
            verdict = ev.get("verdict")
            duration = ev.get("duration_s")
            dur_str = ""
            if duration is not None:
                dur_f = float(duration)
                if dur_f < 60:
                    dur_str = f"{dur_f:.0f}s"
                else:
                    mins = int(dur_f // 60)
                    secs = int(dur_f % 60)
                    dur_str = f"{mins}m {secs}s"
            flat.append(
                FlatEvent(
                    timestamp=ts,
                    cycle=cycle,
                    event_type="worker_reaped",
                    task_id=task_id,
                    detail=f"Reaped {role} for {task_id} ({verdict}, {dur_str})",
                    verdict=str(verdict) if verdict else None,
                    duration_s=float(duration) if duration is not None else None,
                )
            )
        elif event_type == "task_advanced":
            from_phase = ev.get("from_phase") or "start"
            to_phase = ev.get("to_phase") or "end"
            flat.append(
                FlatEvent(
                    timestamp=ts,
                    cycle=cycle,
                    event_type="task_advanced",
                    task_id=task_id,
                    detail=f"{task_id}: {from_phase} → {to_phase}",
                    verdict=None,
                    duration_s=None,
                )
            )
        elif event_type == "intake_ran":
            created = ev.get("created_tasks")
            detail = "Intake: ran PM"
            if created is not None:
                detail = f"Intake: created {created} tasks"
            flat.append(
                FlatEvent(
                    timestamp=ts,
                    cycle=cycle,
                    event_type="intake_ran",
                    task_id=None,
                    detail=detail,
                    verdict=None,
                    duration_s=None,
                )
            )
        elif event_type == "process_improver_ran":
            flat.append(
                FlatEvent(
                    timestamp=ts,
                    cycle=cycle,
                    event_type="process_improver_ran",
                    task_id=None,
                    detail="Process improver ran",
                    verdict=None,
                    duration_s=None,
                )
            )

    # Reverse chronological order (most recent first)
    flat.reverse()
    return flat


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
            tasks_in_flight=[],
            flattened_events=[],
        )

    events = _parse_events(events_path)
    if not events:
        return ActivityResponse(
            current_cycle=0,
            orchestrator_status="unknown",
            active_workers=[],
            cycles=[],
            enabled=False,
            tasks_in_flight=[],
            flattened_events=[],
        )

    cycles = _group_by_cycle(events, since_cycle, limit)
    active_workers = _derive_active_workers(events)
    current_cycle = _derive_current_cycle(events)
    status = _derive_status(events)
    tasks_in_flight = _build_tasks_in_flight(events, active_workers)
    flattened_events = _build_flattened_events(events)

    return ActivityResponse(
        current_cycle=current_cycle,
        orchestrator_status=status,
        active_workers=active_workers,
        cycles=cycles,
        enabled=True,
        tasks_in_flight=tasks_in_flight,
        flattened_events=flattened_events,
    )
