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
                findings_count=0,
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
                findings_count=3,
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
    """cycle_started logs at debug level."""

    def test_logs_at_debug(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.cycle_started(
                cycle=7,
                active_workers=3,
                not_started=2,
                in_progress=3,
                complete=1,
                failed=0,
            )
        assert len(logs) == 1
        assert logs[0]["log_level"] == "debug"
        assert logs[0]["event"] == "cycle_started"


class TestGateChecked:
    """gate_checked log level depends on cleared flag."""

    def test_cleared_true_logs_at_info(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.gate_checked(
                task_id="task-001",
                gate="human-pr-approval",
                cleared=True,
                cycle=5,
            )
        assert len(logs) == 1
        assert logs[0]["log_level"] == "info"

    def test_cleared_false_logs_at_debug(self) -> None:
        with structlog.testing.capture_logs() as logs:
            probe = StructlogProbe()
            probe.gate_checked(
                task_id="task-001",
                gate="human-pr-approval",
                cleared=False,
                cycle=5,
            )
        assert len(logs) == 1
        assert logs[0]["log_level"] == "debug"


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
                findings_count=0,
                detail="All tests pass",
                duration_s=42.5,
            )
        entry = logs[0]
        assert entry["task_id"] == "task-001"
        assert entry["role"] == "verifier"
        assert entry["verdict"] == "pass"
        assert entry["spec_ref"] == "specs/task-001.md"
        assert entry["findings_count"] == 0
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
                findings_count=0,
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
                complete=1,
                failed=0,
                spawned_ids=(),
                reaped_ids=(),
                duration_s=9.8765,
            )
        assert logs[0]["duration_s"] == 9.9
