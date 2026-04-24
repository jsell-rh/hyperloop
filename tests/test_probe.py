"""Tests for NullProbe, MultiProbe, and RecordingProbe.

Exercises the foundational probe infrastructure: NullProbe discards all calls,
MultiProbe fans out to children with error isolation, and RecordingProbe
captures calls for test assertions.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from hyperloop.adapters.probe import MultiProbe, NullProbe
from hyperloop.adapters.probe.file import FileProbe
from hyperloop.ports.probe import OrchestratorProbe
from tests.fakes.probe import RecordingProbe


def _probe_methods() -> tuple[str, ...]:
    """Derive all probe method names from the OrchestratorProbe protocol."""
    return tuple(
        name
        for name, _ in inspect.getmembers(OrchestratorProbe, predicate=inspect.isfunction)
        if not name.startswith("_")
    )


class TestNullProbe:
    """NullProbe accepts all methods without raising."""

    def test_all_methods_accept_kwargs_without_raising(self) -> None:
        """Every method on NullProbe can be called with arbitrary kwargs."""
        probe = NullProbe()
        for method_name in _probe_methods():
            getattr(probe, method_name)(foo="bar", baz=42)

    def test_new_methods_exist(self) -> None:
        """New observability methods are present on NullProbe."""
        probe = NullProbe()
        probe.drift_detected(spec_path="specs/a.md", drift_type="missing", detail="gone")
        probe.audit_ran(spec_ref="specs/a.md", result="pass", cycle=1, duration_s=1.0)
        probe.gc_ran(pruned_count=3, cycle=1)
        probe.convergence_marked(spec_path="specs/a.md", spec_ref="ref-1", cycle=1)
        probe.worker_crash_detected(task_id="t-1", role="impl", branch="hl/t-1")
        probe.step_executed(task_id="t-1", step_name="build", outcome="ok", detail="", cycle=1)
        probe.signal_checked(
            task_id="t-1", signal_name="ci-green", status="pass", message="ok", cycle=1
        )

    def test_renamed_methods_exist(self) -> None:
        """Renamed methods task_retried and signal_checked are present."""
        probe = NullProbe()
        probe.task_retried(task_id="t-1", spec_ref="s", round=1, cycle=1, findings_preview="x")
        probe.signal_checked(task_id="t-1", signal_name="ci", status="pass", message="ok", cycle=1)

    def test_deprecated_methods_still_work(self) -> None:
        """Deprecated methods are kept as backward compat shims."""
        probe = NullProbe()
        probe.rebase_conflict(task_id="t", branch="b", attempt=1, max_attempts=3)
        probe.intake_specs_detected(specs=("s",), cycle=1)
        probe.pr_label_changed(pr_url="u", label="l", added=True)
        probe.branch_pushed(branch="b")
        probe.gate_checked(task_id="t", gate="g", cleared=True, cycle=1)
        probe.task_looped_back(task_id="t", spec_ref="s", round=1, cycle=1, findings_preview="x")

    def test_cycle_started_uses_completed_kwarg(self) -> None:
        """cycle_started accepts 'completed' not 'complete'."""
        probe = NullProbe()
        probe.cycle_started(
            cycle=1, active_workers=0, not_started=5, in_progress=0, completed=0, failed=0
        )


class TestMultiProbe:
    """MultiProbe fans out to children and isolates exceptions."""

    def test_has_every_protocol_method(self) -> None:
        """MultiProbe must implement every method from OrchestratorProbe."""
        multi = MultiProbe((NullProbe(),))
        for method_name in _probe_methods():
            assert hasattr(multi, method_name), (
                f"MultiProbe is missing method '{method_name}' from OrchestratorProbe"
            )
            getattr(multi, method_name)(test_key="test_value")

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

    def test_fans_out_new_methods(self) -> None:
        """New methods are fanned out to children."""
        r1 = RecordingProbe()
        r2 = RecordingProbe()
        multi = MultiProbe((r1, r2))

        multi.drift_detected(spec_path="specs/a.md", drift_type="missing", detail="gone")
        multi.audit_ran(spec_ref="specs/a.md", result="pass", cycle=1, duration_s=1.0)
        multi.gc_ran(pruned_count=3, cycle=1)
        multi.convergence_marked(spec_path="specs/a.md", spec_ref="ref-1", cycle=1)
        multi.worker_crash_detected(task_id="t-1", role="impl", branch="hl/t-1")
        multi.step_executed(task_id="t-1", step_name="build", outcome="ok", detail="", cycle=1)
        multi.signal_checked(
            task_id="t-1", signal_name="ci-green", status="pass", message="ok", cycle=1
        )

        for method in [
            "drift_detected",
            "audit_ran",
            "gc_ran",
            "convergence_marked",
            "worker_crash_detected",
            "step_executed",
            "signal_checked",
        ]:
            assert len(r1.of_method(method)) == 1, f"r1 missing {method}"
            assert len(r2.of_method(method)) == 1, f"r2 missing {method}"

    def test_fans_out_renamed_methods(self) -> None:
        """Renamed methods are fanned out to children."""
        r1 = RecordingProbe()
        multi = MultiProbe((r1,))

        multi.task_retried(task_id="t-1", spec_ref="s", round=1, cycle=1, findings_preview="x")
        assert len(r1.of_method("task_retried")) == 1

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

        multi.cycle_started(cycle=1)

    def test_deprecated_methods_still_work(self) -> None:
        """Deprecated methods are kept as backward compat shims."""
        r1 = RecordingProbe()
        multi = MultiProbe((r1,))
        multi.gate_checked(task_id="t", gate="g", cleared=True, cycle=1)
        multi.task_looped_back(task_id="t", spec_ref="s", round=1, cycle=1, findings_preview="x")
        multi.rebase_conflict(task_id="t", branch="b", attempt=1, max_attempts=3)
        assert len(r1.of_method("gate_checked")) == 1
        assert len(r1.of_method("task_looped_back")) == 1


class TestFileProbe:
    """FileProbe implements all protocol methods and writes JSONL."""

    def test_has_every_protocol_method(self, tmp_path: Path) -> None:
        """FileProbe must implement every method from OrchestratorProbe."""
        probe = FileProbe(tmp_path / "events.jsonl")
        for method_name in _probe_methods():
            assert hasattr(probe, method_name), (
                f"FileProbe is missing method '{method_name}' from OrchestratorProbe"
            )
            getattr(probe, method_name)(test_key="test_value")

    def test_deprecated_methods_still_work(self, tmp_path: Path) -> None:
        """Deprecated methods are kept as backward compat shims."""
        probe = FileProbe(tmp_path / "events.jsonl")
        probe.gate_checked(task_id="t", gate="g", cleared=True, cycle=1)
        probe.task_looped_back(task_id="t", spec_ref="s", round=1, cycle=1, findings_preview="x")
        probe.rebase_conflict(task_id="t", branch="b", attempt=1, max_attempts=3)


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

    def test_all_methods_are_recorded(self) -> None:
        """Every probe method is captured by RecordingProbe."""
        probe = RecordingProbe()
        for method_name in _probe_methods():
            getattr(probe, method_name)(test_key="test_value")

        assert len(probe.calls) == len(_probe_methods())
        recorded_methods = {c.method for c in probe.calls}
        assert recorded_methods == set(_probe_methods())
