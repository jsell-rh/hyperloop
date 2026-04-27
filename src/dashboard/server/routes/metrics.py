"""GET /api/metrics/trend — aggregated metrics over the last N cycles."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter

from dashboard.server.deps import get_repo_path
from dashboard.server.models import (
    ConvergenceTrendPoint,
    ThroughputPoint,
    TrendMetrics,
)
from dashboard.server.routes._events import find_events_path, parse_events

router = APIRouter()


def _compute_trend(events: list[dict[str, Any]], cycles: int) -> TrendMetrics:
    """Compute trend metrics from events over the last N cycles."""
    # Find the max cycle number
    max_cycle = 0
    for ev in events:
        cycle = ev.get("cycle")
        if isinstance(cycle, int) and cycle > max_cycle:
            max_cycle = cycle

    if max_cycle == 0:
        return TrendMetrics(
            cycles_analyzed=0,
            convergence_trend=[],
            task_throughput=[],
            avg_worker_duration_s=None,
            total_tasks_completed=0,
            total_tasks_failed=0,
        )

    # Determine cycle range
    min_cycle = max(1, max_cycle - cycles + 1)
    cycle_range = list(range(min_cycle, max_cycle + 1))

    # Group events by cycle
    by_cycle: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for ev in events:
        cycle = ev.get("cycle")
        if isinstance(cycle, int) and min_cycle <= cycle <= max_cycle:
            by_cycle[cycle].append(ev)

    # Per-cycle metrics
    convergence_trend: list[ConvergenceTrendPoint] = []
    task_throughput: list[ThroughputPoint] = []
    all_durations: list[float] = []
    total_completed = 0
    total_failed = 0

    # Track cumulative convergence across cycles
    converged_specs: set[str] = set()

    for cycle_num in cycle_range:
        evts = by_cycle.get(cycle_num, [])

        # Convergence: count convergence_marked events
        for ev in evts:
            if ev.get("event") == "convergence_marked":
                spec_ref = str(ev.get("spec_ref", ""))
                if spec_ref:
                    converged_specs.add(spec_ref)

        convergence_trend.append(
            ConvergenceTrendPoint(
                cycle=cycle_num,
                converged_count=len(converged_specs),
            )
        )

        # Throughput: count task completions and failures from worker_reaped verdicts
        cycle_completed = 0
        cycle_failed = 0
        for ev in evts:
            if ev.get("event") == "task_completed":
                cycle_completed += 1
            elif ev.get("event") == "task_failed":
                cycle_failed += 1

        task_throughput.append(
            ThroughputPoint(
                cycle=cycle_num,
                completed=cycle_completed,
                failed=cycle_failed,
            )
        )
        total_completed += cycle_completed
        total_failed += cycle_failed

        # Worker durations from worker_reaped events
        for ev in evts:
            if ev.get("event") == "worker_reaped":
                dur = ev.get("duration_s")
                if dur is not None:
                    all_durations.append(float(dur))

    avg_duration = round(sum(all_durations) / len(all_durations), 1) if all_durations else None

    return TrendMetrics(
        cycles_analyzed=len(cycle_range),
        convergence_trend=convergence_trend,
        task_throughput=task_throughput,
        avg_worker_duration_s=avg_duration,
        total_tasks_completed=total_completed,
        total_tasks_failed=total_failed,
    )


@router.get("/api/metrics/trend")
def get_trend_metrics(cycles: int = 20) -> TrendMetrics:
    """Return aggregated metrics over the last N cycles."""
    events_path = find_events_path(get_repo_path())
    if events_path is None or not events_path.exists():
        return TrendMetrics(
            cycles_analyzed=0,
            convergence_trend=[],
            task_throughput=[],
            avg_worker_duration_s=None,
            total_tasks_completed=0,
            total_tasks_failed=0,
        )

    events = parse_events(events_path)
    return _compute_trend(events, cycles)
