"""Tests for StructlogProbe — structured log output for probe calls.

Uses structlog.testing.capture_logs() to capture log entries without I/O.
"""

from __future__ import annotations

import structlog.testing

from hyperloop.adapters.probe.structlog import StructlogProbe


class TestWorkerReaped:
    """worker_reaped log level depends on verdict."""

    def test_pass_verdict_logs_at_info(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.worker_reaped(
                task_id="task-001",
                role="verifier",
                verdict="pass",
                round=0,
                cycle=1,
                spec_ref="specs/task-001.md",
                detail="All tests pass",
                duration_s=42.567,
            )
        assert len(logs) == 1
        assert logs[0]["log_level"] == "info"
        assert logs[0]["event"] == "worker_reaped"

    def test_fail_verdict_logs_at_warning(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.worker_reaped(
                task_id="task-001",
                role="verifier",
                verdict="fail",
                round=1,
                cycle=2,
                spec_ref="specs/task-001.md",
                detail="Tests failed",
                duration_s=55.0,
            )
        assert len(logs) == 1
        assert logs[0]["log_level"] == "warning"


class TestTaskFailed:
    """task_failed logs at error level."""

    def test_logs_at_error(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.task_failed(
                task_id="task-001",
                spec_ref="specs/task-001.md",
                reason="max_rounds exceeded",
                round=50,
                cycle=100,
            )
        assert len(logs) == 1
        assert logs[0]["log_level"] == "error"
        assert logs[0]["event"] == "task_failed"


class TestCycleStarted:
    """cycle_started logs at debug level and uses 'completed' kwarg."""

    def test_logs_at_debug(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.cycle_started(
                cycle=7,
                active_workers=3,
                not_started=2,
                in_progress=3,
                completed=1,
                failed=0,
            )
        assert len(logs) == 1
        assert logs[0]["log_level"] == "debug"
        assert logs[0]["event"] == "cycle_started"


class TestSignalChecked:
    """signal_checked replaces gate_checked with new log level logic."""

    def test_non_pending_status_logs_at_info(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.signal_checked(
                task_id="task-001",
                signal_name="ci-green",
                status="pass",
                message="all checks green",
                cycle=5,
            )
        assert len(logs) == 1
        assert logs[0]["log_level"] == "info"
        assert logs[0]["event"] == "signal_checked"

    def test_pending_status_logs_at_debug(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.signal_checked(
                task_id="task-001",
                signal_name="ci-green",
                status="pending",
                message="waiting",
                cycle=5,
            )
        assert len(logs) == 1
        assert logs[0]["log_level"] == "debug"


class TestTaskRetried:
    """task_retried (renamed from task_looped_back) logs at warning."""

    def test_logs_at_warning(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.task_retried(
                task_id="task-001",
                spec_ref="specs/task-001.md",
                round=2,
                cycle=4,
                findings_preview="test failures",
            )
        assert len(logs) == 1
        assert logs[0]["log_level"] == "warning"
        assert logs[0]["event"] == "task_retried"


class TestNewObservabilityEvents:
    """New probe methods log at correct levels."""

    def test_drift_detected_logs_at_info(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.drift_detected(spec_path="specs/a.md", drift_type="missing", detail="gone")
        assert len(logs) == 1
        assert logs[0]["log_level"] == "info"
        assert logs[0]["event"] == "drift_detected"

    def test_audit_ran_logs_at_info(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.audit_ran(spec_ref="specs/a.md", result="pass", cycle=1, duration_s=1.5)
        assert len(logs) == 1
        assert logs[0]["log_level"] == "info"
        assert logs[0]["event"] == "audit_ran"

    def test_gc_ran_logs_at_info(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.gc_ran(pruned_count=3, cycle=1)
        assert len(logs) == 1
        assert logs[0]["log_level"] == "info"
        assert logs[0]["event"] == "gc_ran"

    def test_convergence_marked_logs_at_info(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.convergence_marked(spec_path="specs/a.md", spec_ref="ref-1", cycle=1)
        assert len(logs) == 1
        assert logs[0]["log_level"] == "info"
        assert logs[0]["event"] == "convergence_marked"

    def test_worker_crash_detected_logs_at_warning(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.worker_crash_detected(task_id="t-1", role="impl", branch="hl/t-1")
        assert len(logs) == 1
        assert logs[0]["log_level"] == "warning"
        assert logs[0]["event"] == "worker_crash_detected"

    def test_step_executed_logs_at_debug(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.step_executed(task_id="t-1", step_name="build", outcome="ok", detail="", cycle=1)
        assert len(logs) == 1
        assert logs[0]["log_level"] == "debug"
        assert logs[0]["event"] == "step_executed"


class TestLogEntryContainsAllKwargs:
    """Log entries contain all kwargs as keys."""

    def test_worker_reaped_has_all_fields(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.worker_reaped(
                task_id="task-001",
                role="verifier",
                verdict="pass",
                round=0,
                cycle=1,
                spec_ref="specs/task-001.md",
                detail="All tests pass",
                duration_s=42.5,
            )
        entry = logs[0]
        assert entry["task_id"] == "task-001"
        assert entry["role"] == "verifier"
        assert entry["verdict"] == "pass"
        assert entry["spec_ref"] == "specs/task-001.md"
        assert entry["detail"] == "All tests pass"


class TestDurationRounding:
    """duration_s is rounded to 1 decimal place."""

    def test_duration_rounded_in_worker_reaped(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.worker_reaped(
                task_id="task-001",
                role="verifier",
                verdict="pass",
                round=0,
                cycle=1,
                spec_ref="specs/task-001.md",
                detail="ok",
                duration_s=142.3456,
            )
        assert logs[0]["duration_s"] == 142.3

    def test_duration_rounded_in_cycle_completed(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.cycle_completed(
                cycle=1,
                active_workers=0,
                not_started=0,
                in_progress=0,
                completed=1,
                failed=0,
                spawned_ids=(),
                reaped_ids=(),
                duration_s=9.8765,
            )
        assert logs[0]["duration_s"] == 9.9

    def test_duration_rounded_in_audit_ran(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.audit_ran(spec_ref="s", result="pass", cycle=1, duration_s=3.456)
        assert logs[0]["duration_s"] == 3.5
