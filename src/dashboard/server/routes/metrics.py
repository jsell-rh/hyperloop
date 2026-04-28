"""GET /api/metrics/* — aggregated metrics and KPI visualizations."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter

from dashboard.server.deps import get_repo_path
from dashboard.server.models import (
    BurndownPoint,
    BurndownResponse,
    ConvergenceTrendPoint,
    KpiCard,
    KpiResponse,
    PhaseFunnelEntry,
    PhaseFunnelResponse,
    RoundDistributionBucket,
    RoundEfficiencyPoint,
    RoundEfficiencyResponse,
    SparklinePoint,
    ThroughputPoint,
    TrendMetrics,
    VelocityPoint,
    VelocityResponse,
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


# ---------------------------------------------------------------------------
# Helpers shared by visualization endpoints
# ---------------------------------------------------------------------------


def _load_session_events() -> list[dict[str, Any]]:
    """Load events for the latest orchestrator session."""
    events_path = find_events_path(get_repo_path())
    if events_path is None or not events_path.exists():
        return []
    events = parse_events(events_path)
    if not events:
        return []
    # Trim to latest orchestrator session (same logic as activity.py)
    last_start_idx = 0
    for i, ev in enumerate(events):
        if ev.get("event") == "orchestrator_started":
            last_start_idx = i
    if last_start_idx > 0:
        events = events[last_start_idx:]
    return events


def _group_events_by_cycle(
    events: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    """Group events by cycle number, returning sorted dict."""
    by_cycle: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for ev in events:
        cycle = ev.get("cycle")
        if isinstance(cycle, int):
            by_cycle[cycle].append(ev)
    return dict(sorted(by_cycle.items()))


def _cycle_range(by_cycle: dict[int, list[dict[str, Any]]], n: int) -> list[int]:
    """Return the last N cycle numbers, sorted ascending."""
    all_cycles = sorted(by_cycle.keys())
    return all_cycles[-n:] if len(all_cycles) > n else all_cycles


# ---------------------------------------------------------------------------
# GET /api/metrics/kpi — 6 KPI summary cards
# ---------------------------------------------------------------------------


def _compute_kpi(events: list[dict[str, Any]]) -> KpiResponse:
    """Compute all 6 KPI cards from events.

    Cards gracefully degrade: when ``task_completed`` events exist, show
    task-level stats.  Otherwise fall back to round-level stats from
    ``worker_reaped`` so the dashboard never shows "0" when useful
    intermediate data is available.
    """
    by_cycle = _group_events_by_cycle(events)
    last_20 = _cycle_range(by_cycle, 20)

    # Per-cycle accumulators
    reaped_per_cycle: list[int] = []
    verify_pass_per_cycle: list[int] = []
    verify_total_per_cycle: list[int] = []
    drift_per_cycle: list[int] = []
    pass_per_cycle: list[int] = []
    fail_per_cycle: list[int] = []

    for cycle_num in last_20:
        evts = by_cycle.get(cycle_num, [])
        reaped = 0
        v_pass = 0
        v_total = 0
        drift = 0
        cycle_pass = 0
        cycle_fail = 0

        for ev in evts:
            event_type = ev.get("event")
            if event_type == "worker_reaped":
                reaped += 1
                verdict = ev.get("verdict")
                role = str(ev.get("role", ""))
                if verdict == "pass":
                    cycle_pass += 1
                elif verdict == "fail":
                    cycle_fail += 1
                # Verifier-specific pass rate
                if role == "verifier":
                    v_total += 1
                    if verdict == "pass":
                        v_pass += 1
            elif event_type == "reconcile_completed":
                dc = ev.get("drift_count")
                if isinstance(dc, int):
                    drift = dc

        reaped_per_cycle.append(reaped)
        verify_pass_per_cycle.append(v_pass)
        verify_total_per_cycle.append(v_total)
        drift_per_cycle.append(drift)
        pass_per_cycle.append(cycle_pass)
        fail_per_cycle.append(cycle_fail)

    total_reaped = sum(reaped_per_cycle)
    total_verify_pass = sum(verify_pass_per_cycle)
    total_verify = sum(verify_total_per_cycle)
    total_pass = sum(pass_per_cycle)
    total_fail = sum(fail_per_cycle)

    # ---- Card 1: Rounds Completed ----
    # Count worker_reaped events (each represents a completed round of work).
    reaped_sparkline = [
        SparklinePoint(cycle=last_20[i], value=float(reaped_per_cycle[i]))
        for i in range(len(last_20))
    ]

    # ---- Card 2: Verify Pass Rate ----
    # Percentage of verifier worker_reaped events with verdict == "pass".
    verify_pass_rate = 0.0
    if total_verify > 0:
        verify_pass_rate = round(total_verify_pass / total_verify * 100, 1)
    verify_rate_per_cycle: list[float] = []
    for i in range(len(last_20)):
        if verify_total_per_cycle[i] > 0:
            verify_rate_per_cycle.append(
                round(verify_pass_per_cycle[i] / verify_total_per_cycle[i] * 100, 1)
            )
        else:
            verify_rate_per_cycle.append(0.0)
    verify_sparkline = [
        SparklinePoint(cycle=last_20[i], value=verify_rate_per_cycle[i])
        for i in range(len(last_20))
    ]

    # ---- Card 3: Specs Converged ----
    drift_remaining = 0
    total_specs = 0
    for ev in reversed(events):
        if ev.get("event") == "reconcile_completed":
            dc = ev.get("drift_count")
            if isinstance(dc, int):
                drift_remaining = dc
            ts = ev.get("total_specs")
            if isinstance(ts, int):
                total_specs = ts
            break

    if total_specs == 0:
        spec_refs: set[str] = set()
        for ev in events:
            if ev.get("event") == "audit_ran":
                sr = ev.get("spec_ref")
                if isinstance(sr, str) and sr:
                    spec_refs.add(sr)
        total_specs = len(spec_refs)

    # Also count convergence_marked events for a more accurate number
    converged_specs: set[str] = set()
    for ev in events:
        if ev.get("event") == "convergence_marked":
            sp = ev.get("spec_ref") or ev.get("spec_path")
            if isinstance(sp, str) and sp:
                converged_specs.add(sp)
    if converged_specs:
        specs_converged = len(converged_specs)
    else:
        specs_converged = max(0, total_specs - drift_remaining)

    # ---- Card 4: Active Workers ----
    latest_workers: dict[str, bool] = {}
    for ev in events:
        event_type = ev.get("event")
        task_id = str(ev.get("task_id", ""))
        if event_type == "worker_spawned" and task_id:
            latest_workers[task_id] = True
        elif event_type == "worker_reaped" and task_id:
            latest_workers[task_id] = False
    active_workers_count = sum(1 for v in latest_workers.values() if v)

    # ---- Card 5: Merge Rate ----
    # Pass/fail ratio of all worker_reaped events in last 20 cycles.
    total_decided = total_pass + total_fail
    merge_rate = 0.0
    if total_decided > 0:
        merge_rate = round(total_pass / total_decided * 100, 1)
    merge_sparkline_values: list[float] = []
    for i in range(len(last_20)):
        decided = pass_per_cycle[i] + fail_per_cycle[i]
        if decided > 0:
            merge_sparkline_values.append(round(pass_per_cycle[i] / decided * 100, 1))
        else:
            merge_sparkline_values.append(0.0)
    merge_sparkline = [
        SparklinePoint(cycle=last_20[i], value=merge_sparkline_values[i])
        for i in range(len(last_20))
    ]

    # ---- Card 6: Drift Remaining ----
    drift_sparkline = [
        SparklinePoint(cycle=last_20[i], value=float(drift_per_cycle[i]))
        for i in range(len(last_20))
    ]

    # ---- Trend helper ----
    def trend_direction(values: list[float], higher_is_better: bool) -> tuple[str, bool]:
        if len(values) < 4:
            return "flat", True
        mid = len(values) // 2
        first_half = sum(values[:mid]) / mid if mid > 0 else 0
        second_half = sum(values[mid:]) / (len(values) - mid) if (len(values) - mid) > 0 else 0
        diff = second_half - first_half
        threshold = max(abs(first_half) * 0.05, 0.1)  # 5% or 0.1
        if abs(diff) < threshold:
            return "flat", True
        if diff > 0:
            return "up", higher_is_better
        return "down", not higher_is_better

    reaped_trend, reaped_good = trend_direction(
        [float(r) for r in reaped_per_cycle], higher_is_better=True
    )
    verify_trend, verify_good = trend_direction(verify_rate_per_cycle, higher_is_better=True)
    drift_vals = [float(d) for d in drift_per_cycle]
    drift_trend, drift_good = trend_direction(drift_vals, higher_is_better=False)
    merge_trend, merge_good = trend_direction(merge_sparkline_values, higher_is_better=True)

    cards: list[KpiCard] = [
        KpiCard(
            label="Rounds Completed",
            value=float(total_reaped),
            unit="rounds",
            sparkline=reaped_sparkline,
            trend=reaped_trend,
            trend_is_good=reaped_good,
        ),
        KpiCard(
            label="Verify Pass Rate",
            value=verify_pass_rate,
            unit="%",
            sparkline=verify_sparkline,
            trend=verify_trend,
            trend_is_good=verify_good,
        ),
        KpiCard(
            label="Specs Converged",
            value=float(specs_converged),
            unit=f"/ {total_specs}",
            sparkline=[],
            trend="flat",
            trend_is_good=True,
        ),
        KpiCard(
            label="Active Workers",
            value=float(active_workers_count),
            unit="workers",
            sparkline=[],
            trend="flat",
            trend_is_good=True,
        ),
        KpiCard(
            label="Merge Rate",
            value=merge_rate,
            unit="%",
            sparkline=merge_sparkline,
            trend=merge_trend,
            trend_is_good=merge_good,
        ),
        KpiCard(
            label="Drift Remaining",
            value=float(drift_remaining),
            unit="specs",
            sparkline=drift_sparkline,
            trend=drift_trend,
            trend_is_good=drift_good,
        ),
    ]

    return KpiResponse(cards=cards)


@router.get("/api/metrics/kpi")
def get_kpi() -> KpiResponse:
    """Return all 6 KPI card values with sparklines and trends."""
    events = _load_session_events()
    if not events:
        return KpiResponse(cards=[])
    return _compute_kpi(events)


# ---------------------------------------------------------------------------
# GET /api/metrics/burndown — burnup/burndown chart
# ---------------------------------------------------------------------------


def _compute_burndown(events: list[dict[str, Any]]) -> BurndownResponse:
    """Compute burnup/burndown time series."""
    by_cycle = _group_events_by_cycle(events)
    points: list[BurndownPoint] = []
    cumulative_completed = 0

    for cycle_num in sorted(by_cycle.keys()):
        evts = by_cycle[cycle_num]
        completed_this = 0
        drift = 0
        scope_change = False
        timestamp = ""

        for ev in evts:
            event_type = ev.get("event")
            if event_type == "task_completed":
                completed_this += 1
            elif event_type == "reconcile_completed":
                dc = ev.get("drift_count")
                if isinstance(dc, int):
                    drift = dc
            elif event_type == "intake_ran":
                ct = ev.get("created_tasks")
                if isinstance(ct, int) and ct > 0:
                    scope_change = True
            elif event_type == "cycle_started":
                timestamp = str(ev.get("ts", ""))

        if not timestamp and evts:
            timestamp = str(evts[0].get("ts", ""))

        cumulative_completed += completed_this
        points.append(
            BurndownPoint(
                cycle=cycle_num,
                timestamp=timestamp,
                burnup=cumulative_completed,
                burndown=drift,
                scope_change=scope_change,
            )
        )

    return BurndownResponse(points=points)


@router.get("/api/metrics/burndown")
def get_burndown() -> BurndownResponse:
    """Return time series for burnup/burndown chart."""
    events = _load_session_events()
    if not events:
        return BurndownResponse(points=[])
    return _compute_burndown(events)


# ---------------------------------------------------------------------------
# GET /api/metrics/velocity — task completion velocity
# ---------------------------------------------------------------------------


def _compute_velocity(events: list[dict[str, Any]]) -> VelocityResponse:
    """Compute rolling velocity (tasks completed per hour)."""
    by_cycle = _group_events_by_cycle(events)
    sorted_cycles = sorted(by_cycle.keys())
    points: list[VelocityPoint] = []

    # Use a sliding window of 10 cycles
    window_size = 10
    for i in range(len(sorted_cycles)):
        window_start = max(0, i - window_size + 1)
        window_cycles = sorted_cycles[window_start : i + 1]

        completed_count = 0
        first_ts = ""
        last_ts = ""

        for cycle_num in window_cycles:
            evts = by_cycle[cycle_num]
            for ev in evts:
                if ev.get("event") == "task_completed":
                    completed_count += 1
                ts = str(ev.get("ts", ""))
                if ts:
                    if not first_ts or ts < first_ts:
                        first_ts = ts
                    if not last_ts or ts > last_ts:
                        last_ts = ts

        # Calculate hours elapsed
        hours = 0.0
        if first_ts and last_ts:
            try:
                from datetime import datetime

                t1 = datetime.fromisoformat(first_ts)
                t2 = datetime.fromisoformat(last_ts)
                hours = max((t2 - t1).total_seconds() / 3600, 0.001)
            except (ValueError, TypeError):
                hours = 1.0
        else:
            hours = 1.0

        tasks_per_hour = round(completed_count / hours, 2) if hours > 0 else 0.0

        timestamp = ""
        current_evts = by_cycle.get(sorted_cycles[i], [])
        for ev in current_evts:
            if ev.get("event") == "cycle_started":
                timestamp = str(ev.get("ts", ""))
                break
        if not timestamp and current_evts:
            timestamp = str(current_evts[0].get("ts", ""))

        points.append(
            VelocityPoint(
                cycle=sorted_cycles[i],
                timestamp=timestamp,
                tasks_per_hour=tasks_per_hour,
                completed_count=completed_count,
            )
        )

    return VelocityResponse(points=points)


@router.get("/api/metrics/velocity")
def get_velocity() -> VelocityResponse:
    """Return velocity data points over time."""
    events = _load_session_events()
    if not events:
        return VelocityResponse(points=[])
    return _compute_velocity(events)


# ---------------------------------------------------------------------------
# GET /api/metrics/round-efficiency — round efficiency trend + distribution
# ---------------------------------------------------------------------------


def _compute_round_efficiency(
    events: list[dict[str, Any]],
) -> RoundEfficiencyResponse:
    """Compute round efficiency trend and distribution."""
    by_cycle = _group_events_by_cycle(events)
    sorted_cycles = sorted(by_cycle.keys())

    # Collect all total_rounds values
    all_rounds: list[tuple[int, int]] = []  # (cycle, total_rounds)
    for cycle_num in sorted_cycles:
        for ev in by_cycle[cycle_num]:
            if ev.get("event") == "task_completed":
                tr = ev.get("total_rounds")
                if isinstance(tr, int):
                    all_rounds.append((cycle_num, tr))

    # Trend: group by 10-cycle windows
    window_size = 10
    trend: list[RoundEfficiencyPoint] = []
    if sorted_cycles:
        for i in range(0, len(sorted_cycles), window_size):
            window_cycles = set(sorted_cycles[i : i + window_size])
            window_rounds = [r for c, r in all_rounds if c in window_cycles]
            if window_rounds:
                trend.append(
                    RoundEfficiencyPoint(
                        window_start=sorted_cycles[i],
                        window_end=sorted_cycles[min(i + window_size - 1, len(sorted_cycles) - 1)],
                        avg_rounds=round(sum(window_rounds) / len(window_rounds), 2),
                        sample_count=len(window_rounds),
                    )
                )

    # Distribution: count tasks by rounds bucket
    buckets: dict[str, int] = {"1": 0, "2": 0, "3": 0, "4": 0, "5+": 0}
    for _, rounds in all_rounds:
        if rounds >= 5:
            buckets["5+"] += 1
        else:
            buckets[str(rounds)] += 1

    distribution = [RoundDistributionBucket(rounds=k, count=v) for k, v in buckets.items()]

    return RoundEfficiencyResponse(trend=trend, distribution=distribution)


@router.get("/api/metrics/round-efficiency")
def get_round_efficiency() -> RoundEfficiencyResponse:
    """Return round efficiency trend and distribution."""
    events = _load_session_events()
    if not events:
        return RoundEfficiencyResponse(trend=[], distribution=[])
    return _compute_round_efficiency(events)


# ---------------------------------------------------------------------------
# GET /api/metrics/phase-funnel — per-phase stats
# ---------------------------------------------------------------------------


def _compute_phase_funnel(events: list[dict[str, Any]]) -> PhaseFunnelResponse:
    """Compute per-phase duration and success rate."""
    # Gather worker_reaped events grouped by role (role = phase)
    role_durations: dict[str, list[float]] = defaultdict(list)
    role_executions: dict[str, int] = defaultdict(int)

    for ev in events:
        if ev.get("event") == "worker_reaped":
            role = str(ev.get("role", ""))
            if not role:
                continue
            role_executions[role] += 1
            dur = ev.get("duration_s")
            if dur is not None:
                role_durations[role].append(float(dur))

    # Gather task_advanced events to compute first-pass success rate
    # First pass = round 1 advance from that phase
    phase_advances: dict[str, int] = defaultdict(int)
    phase_retries: dict[str, int] = defaultdict(int)

    for ev in events:
        event_type = ev.get("event")
        if event_type == "task_advanced":
            from_phase = ev.get("from_phase")
            if isinstance(from_phase, str) and from_phase:
                phase_advances[from_phase] += 1
        elif event_type == "worker_reaped":
            role = str(ev.get("role", ""))
            verdict = ev.get("verdict")
            if role and verdict == "fail":
                phase_retries[role] += 1

    # Build phase entries (preserve order of appearance)
    seen_roles: list[str] = []
    for ev in events:
        if ev.get("event") == "worker_reaped":
            role = str(ev.get("role", ""))
            if role and role not in seen_roles:
                seen_roles.append(role)

    phases: list[PhaseFunnelEntry] = []
    for role in seen_roles:
        durations = role_durations.get(role, [])
        avg_dur = round(sum(durations) / len(durations), 1) if durations else 0.0
        total_exec = role_executions.get(role, 0)
        advances = phase_advances.get(role, 0)
        retries = phase_retries.get(role, 0)
        total_attempts = advances + retries
        success_rate = round(advances / total_attempts * 100, 1) if total_attempts > 0 else 0.0

        phases.append(
            PhaseFunnelEntry(
                phase=role,
                avg_duration_s=avg_dur,
                total_executions=total_exec,
                first_pass_success_rate=success_rate,
            )
        )

    return PhaseFunnelResponse(phases=phases)


@router.get("/api/metrics/phase-funnel")
def get_phase_funnel() -> PhaseFunnelResponse:
    """Return per-phase stats for funnel visualization."""
    events = _load_session_events()
    if not events:
        return PhaseFunnelResponse(phases=[])
    return _compute_phase_funnel(events)
