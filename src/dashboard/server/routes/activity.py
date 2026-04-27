"""Activity API — cycle-by-cycle reconciliation log from FileProbe events."""

from __future__ import annotations

import contextlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter

from dashboard.server.deps import get_repo_path, get_state
from dashboard.server.models import (
    ActiveWorker,
    ActivityResponse,
    AdvancePhase,
    AuditDetail,
    AuditEntry,
    AuditTimeline,
    CollectPhase,
    CycleDetail,
    CyclePhases,
    FlatEvent,
    HeartbeatResponse,
    IntakePhase,
    PhaseTransition,
    ReapedWorker,
    ReconcileDetail,
    SpawnedWorker,
    SpawnPhase,
    TaskInFlight,
    WorkerHeartbeat,
    WorkerHistoryEntry,
)
from dashboard.server.routes._events import find_events_path, parse_events

router = APIRouter()

_STALE_THRESHOLD_S = 120.0


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

    # RECONCILE: build reconcile detail from probe events
    reconcile = _build_reconcile_detail(evts)

    # AUDIT TIMELINE: build Gantt chart data from audit_started / audit_ran
    audit_timeline = _build_audit_timeline(evts)

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
        reconcile=reconcile,
        audit_timeline=audit_timeline,
    )


def _build_reconcile_detail(evts: list[dict[str, Any]]) -> ReconcileDetail | None:
    """Build reconcile detail from reconcile_*, audit_ran, drift_detected, gc_ran events.

    Returns None if no reconcile events exist in this cycle.
    """
    # Reconcile duration from reconcile_completed
    reconcile_duration_s: float | None = None
    drift_count: int | None = None
    gc_pruned_from_summary: int | None = None

    for ev in evts:
        if ev.get("event") == "reconcile_completed":
            reconcile_duration_s = ev.get("duration_s")
            raw_drift = ev.get("drift_count")
            if raw_drift is not None:
                drift_count = int(raw_drift)
            raw_gc = ev.get("gc_pruned")
            if raw_gc is not None:
                gc_pruned_from_summary = int(raw_gc)

    # Collect audit details from audit_ran events
    audits: list[AuditDetail] = []
    for ev in evts:
        if ev.get("event") == "audit_ran":
            audits.append(
                AuditDetail(
                    spec_ref=str(ev.get("spec_ref", "")),
                    result=str(ev.get("result", "")),
                    duration_s=float(ev.get("duration_s", 0.0)),
                )
            )

    # Count drifts from drift_detected events if not available from summary
    if drift_count is None:
        drift_count = sum(1 for ev in evts if ev.get("event") == "drift_detected")

    # Count gc_pruned from gc_ran events if not available from summary
    if gc_pruned_from_summary is None:
        for ev in evts:
            if ev.get("event") == "gc_ran":
                raw = ev.get("pruned_count")
                if raw is not None:
                    gc_pruned_from_summary = int(raw)

    # Only return reconcile detail if there are any reconcile-related events
    has_reconcile_events = (
        reconcile_duration_s is not None
        or audits
        or drift_count > 0
        or (gc_pruned_from_summary is not None and gc_pruned_from_summary > 0)
    )
    if not has_reconcile_events:
        return None

    return ReconcileDetail(
        drift_count=drift_count,
        audits=audits,
        gc_pruned=gc_pruned_from_summary or 0,
        reconcile_duration_s=reconcile_duration_s,
    )


def _build_audit_timeline(evts: list[dict[str, Any]]) -> AuditTimeline | None:
    """Build an audit timeline from audit_started and audit_ran events.

    Pairs audit_started with audit_ran by spec_ref to determine start time
    and duration. Returns None if no audit events exist in this cycle.
    """
    # Collect start timestamps per spec_ref
    started_ts: dict[str, str] = {}
    for ev in evts:
        if ev.get("event") == "audit_started":
            spec_ref = str(ev.get("spec_ref", ""))
            ts = str(ev.get("ts", ""))
            if spec_ref and ts:
                started_ts[spec_ref] = ts

    # Collect completed audit results
    entries: list[AuditEntry] = []
    for ev in evts:
        if ev.get("event") == "audit_ran":
            spec_ref = str(ev.get("spec_ref", ""))
            result = str(ev.get("result", ""))
            duration_s = float(ev.get("duration_s", 0.0))
            # Use audit_started timestamp if available, otherwise fall back to
            # the audit_ran timestamp minus duration
            ts_ran = str(ev.get("ts", ""))
            ts_start = started_ts.get(spec_ref, "")
            if not ts_start and ts_ran:
                # Approximate start time by subtracting duration
                try:
                    ran_dt = datetime.fromisoformat(ts_ran)
                    start_dt = ran_dt - timedelta(seconds=duration_s)
                    ts_start = start_dt.isoformat()
                except (ValueError, TypeError):
                    ts_start = ts_ran

            entries.append(
                AuditEntry(
                    spec_ref=spec_ref,
                    result=result,
                    started_at=ts_start or ts_ran,
                    duration_s=duration_s,
                )
            )

    if not entries:
        return None

    total_duration_s = max(e.duration_s for e in entries)

    # Calculate max parallelism: count overlapping time intervals
    max_parallelism = _compute_max_parallelism(entries)

    return AuditTimeline(
        entries=entries,
        total_duration_s=round(total_duration_s, 1),
        max_parallelism=max_parallelism,
    )


def _compute_max_parallelism(entries: list[AuditEntry]) -> int:
    """Compute the maximum number of concurrently running auditors.

    Uses a sweep-line algorithm over start/end time boundaries.
    """
    if not entries:
        return 0

    # Build a list of (time, delta) events: +1 at start, -1 at end
    boundaries: list[tuple[str, int]] = []
    for entry in entries:
        start = entry.started_at
        try:
            end_dt = datetime.fromisoformat(start) + timedelta(seconds=entry.duration_s)
            end = end_dt.isoformat()
        except (ValueError, TypeError):
            end = start
        boundaries.append((start, 1))
        boundaries.append((end, -1))

    # Sort by time; ties broken so that starts (+1) come before ends (-1)
    boundaries.sort(key=lambda b: (b[0], b[1]))

    max_concurrent = 0
    current = 0
    for _, delta in boundaries:
        current += delta
        if current > max_concurrent:
            max_concurrent = current

    return max_concurrent


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
    events_path = find_events_path(get_repo_path())
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

    events = parse_events(events_path)
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


@router.get("/api/activity/worker-heartbeats")
def get_worker_heartbeats(since: str | None = None) -> HeartbeatResponse:
    """Lightweight endpoint for worker liveness animations.

    Reads only the tail of the events JSONL file for speed (sub-50ms target).
    """
    events_path = find_events_path(get_repo_path())
    if not events_path or not events_path.exists():
        return HeartbeatResponse(heartbeats=[], server_time=datetime.now(UTC).isoformat())

    # Read only the tail of the file for speed
    try:
        content = events_path.read_text()
        lines = content.strip().splitlines()[-200:]  # last 200 lines
    except OSError:
        return HeartbeatResponse(heartbeats=[], server_time=datetime.now(UTC).isoformat())

    since_dt: datetime | None = None
    if since:
        with contextlib.suppress(ValueError):
            since_dt = datetime.fromisoformat(since)

    # Group worker_message events by task_id
    per_task: dict[str, list[dict[str, Any]]] = {}
    for line in lines:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event") != "worker_message":
            continue
        task_id = ev.get("task_id", "")
        if not task_id or task_id.startswith("serial-"):
            continue
        ts = ev.get("ts", "")
        if since_dt and ts:
            try:
                if datetime.fromisoformat(ts) <= since_dt:
                    continue
            except ValueError:
                pass
        per_task.setdefault(task_id, []).append(ev)

    now = datetime.now(UTC)
    heartbeats: list[WorkerHeartbeat] = []
    for task_id, messages in per_task.items():
        if not messages:
            continue
        last = messages[-1]
        last_ts = last.get("ts", "")
        seconds_since = 0.0
        if last_ts:
            with contextlib.suppress(ValueError):
                seconds_since = (now - datetime.fromisoformat(last_ts)).total_seconds()

        # Determine tool name from message_type and content
        msg_type = str(last.get("message_type", ""))
        content = str(last.get("content", ""))
        tool_name: str | None = None
        if msg_type == "tool_use":
            tool_name = content.split()[0] if content else None

        heartbeats.append(
            WorkerHeartbeat(
                task_id=task_id,
                role=str(last.get("role", "")),
                last_message_at=last_ts,
                last_message_type=msg_type,
                last_tool_name=tool_name,
                message_count_since=len(messages),
                seconds_since_last=round(seconds_since, 1),
            )
        )

    return HeartbeatResponse(heartbeats=heartbeats, server_time=now.isoformat())
