"""Tests for NullProbe, MultiProbe, and RecordingProbe.

Exercises the foundational probe infrastructure: NullProbe discards all calls,
MultiProbe fans out to children with error isolation, and RecordingProbe
captures calls for test assertions.
"""

from __future__ import annotations

from hyperloop.adapters.probe import MultiProbe, NullProbe
from tests.fakes.probe import RecordingProbe

# All 17 probe method names for exhaustive testing
ALL_METHODS = (
    "orchestrator_started",
    "orchestrator_halted",
    "cycle_started",
    "cycle_completed",
    "worker_spawned",
    "worker_reaped",
    "task_advanced",
    "task_looped_back",
    "task_completed",
    "task_failed",
    "gate_checked",
    "merge_attempted",
    "rebase_conflict",
    "intake_ran",
    "process_improver_ran",
    "recovery_started",
    "orphan_found",
)


class TestNullProbe:
    """NullProbe accepts all 17 methods without raising."""

    def test_all_methods_accept_kwargs_without_raising(self) -> None:
        """Every method on NullProbe can be called with arbitrary kwargs."""
        probe = NullProbe()
        for method_name in ALL_METHODS:
            getattr(probe, method_name)(foo="bar", baz=42)
        # No exception = pass


class TestMultiProbe:
    """MultiProbe fans out to children and isolates exceptions."""

    def test_fans_out_to_two_recording_probes(self) -> None:
        """Both children receive the call with correct kwargs."""
        r1 = RecordingProbe()
        r2 = RecordingProbe()
        multi = MultiProbe((r1, r2))

        multi.worker_reaped(task_id="task-001", verdict="pass", duration_s=1.5)

        assert len(r1.of_method("worker_reaped")) == 1
        assert len(r2.of_method("worker_reaped")) == 1
        assert r1.last("worker_reaped")["task_id"] == "task-001"
        assert r2.last("worker_reaped")["verdict"] == "pass"

    def test_exception_in_one_child_does_not_block_other(self) -> None:
        """If one child raises, the other still receives the call."""

        class BrokenProbe:
            """Probe that raises on every call."""

            def worker_reaped(self, **_kw: object) -> None:
                msg = "boom"
                raise RuntimeError(msg)

        broken = BrokenProbe()
        healthy = RecordingProbe()
        multi = MultiProbe((broken, healthy))  # type: ignore[arg-type]

        # Should not raise — exception is caught
        multi.worker_reaped(task_id="task-001", verdict="fail")

        assert len(healthy.of_method("worker_reaped")) == 1
        assert healthy.last("worker_reaped")["verdict"] == "fail"

    def test_exception_is_swallowed(self) -> None:
        """Exception in a child probe is swallowed, not propagated."""

        class BrokenProbe:
            def cycle_started(self, **_kw: object) -> None:
                msg = "kaboom"
                raise ValueError(msg)

        broken = BrokenProbe()
        multi = MultiProbe((broken,))  # type: ignore[arg-type]

        # Should not raise — exception is caught and logged internally
        multi.cycle_started(cycle=1)


class TestRecordingProbe:
    """RecordingProbe captures calls for test assertions."""

    def test_of_method_returns_correct_data(self) -> None:
        """of_method returns kwargs of all calls to the named method."""
        probe = RecordingProbe()
        probe.worker_reaped(task_id="task-001", verdict="pass")
        probe.worker_reaped(task_id="task-002", verdict="fail")
        probe.task_completed(task_id="task-003")

        reaped = probe.of_method("worker_reaped")
        assert len(reaped) == 2
        assert reaped[0]["task_id"] == "task-001"
        assert reaped[1]["task_id"] == "task-002"

    def test_last_returns_most_recent_call(self) -> None:
        """last returns kwargs of the most recent call to the named method."""
        probe = RecordingProbe()
        probe.cycle_started(cycle=1, active_workers=0)
        probe.cycle_started(cycle=2, active_workers=3)

        last = probe.last("cycle_started")
        assert last["cycle"] == 2
        assert last["active_workers"] == 3

    def test_last_raises_assertion_error_for_uncalled_method(self) -> None:
        """last raises AssertionError when the method was never called."""
        import pytest

        probe = RecordingProbe()

        with pytest.raises(AssertionError, match="No calls to 'worker_reaped'"):
            probe.last("worker_reaped")

    def test_runtime_metrics_flow_through_worker_reaped(self) -> None:
        """Runtime metrics (cost, turns, API duration) are captured in kwargs."""
        probe = RecordingProbe()
        probe.worker_reaped(
            task_id="task-001",
            verdict="pass",
            cost_usd=0.42,
            num_turns=7,
            api_duration_ms=8500.0,
        )

        last = probe.last("worker_reaped")
        assert last["cost_usd"] == 0.42
        assert last["num_turns"] == 7
        assert last["api_duration_ms"] == 8500.0

    def test_runtime_metrics_none_by_default(self) -> None:
        """When runtime metrics are not passed, they are absent from kwargs."""
        probe = RecordingProbe()
        probe.worker_reaped(task_id="task-001", verdict="pass")

        last = probe.last("worker_reaped")
        assert "cost_usd" not in last
        assert "num_turns" not in last
        assert "api_duration_ms" not in last

    def test_all_17_methods_are_recorded(self) -> None:
        """Every probe method is captured by RecordingProbe."""
        probe = RecordingProbe()
        for method_name in ALL_METHODS:
            getattr(probe, method_name)(test_key="test_value")

        assert len(probe.calls) == len(ALL_METHODS)
        recorded_methods = {c.method for c in probe.calls}
        assert recorded_methods == set(ALL_METHODS)
