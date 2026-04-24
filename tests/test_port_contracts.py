"""Contract tests for new port fakes: StepExecutor, SignalPort, ChannelPort.

These tests verify the fakes implement the full port contract correctly.
Structured for future parameterization against real adapters.
"""

from __future__ import annotations

from hyperloop.domain.model import (
    Signal,
    SignalStatus,
    StepOutcome,
    StepResult,
    Task,
    TaskStatus,
)
from tests.fakes.channel import FakeChannelPort
from tests.fakes.probe import RecordingProbe
from tests.fakes.signal import FakeSignalPort
from tests.fakes.step_executor import FakeStepExecutor


def _make_task(task_id: str = "task-001") -> Task:
    return Task(
        id=task_id,
        title="Test task",
        spec_ref="specs/test.md",
        status=TaskStatus.IN_PROGRESS,
        phase=None,
        deps=(),
        round=1,
        branch="hyperloop/task-001",
        pr=None,
    )


# ---------------------------------------------------------------------------
# FakeStepExecutor contract tests
# ---------------------------------------------------------------------------


class TestStepExecutorDefaultResult:
    def test_returns_default_when_no_result_configured(self) -> None:
        executor = FakeStepExecutor()
        task = _make_task()

        result = executor.execute(task, "merge", {})

        assert result.outcome == StepOutcome.ADVANCE
        assert result.detail == "OK"

    def test_custom_default(self) -> None:
        executor = FakeStepExecutor()
        executor.set_default(StepResult(outcome=StepOutcome.WAIT, detail="waiting"))
        task = _make_task()

        result = executor.execute(task, "any-step", {})

        assert result.outcome == StepOutcome.WAIT
        assert result.detail == "waiting"


class TestStepExecutorConfiguredResult:
    def test_returns_configured_result_for_task_and_step(self) -> None:
        executor = FakeStepExecutor()
        expected = StepResult(outcome=StepOutcome.RETRY, detail="CI failed")
        executor.set_result("task-001", "lint", expected)
        task = _make_task()

        result = executor.execute(task, "lint", {"verbose": True})

        assert result.outcome == StepOutcome.RETRY
        assert result.detail == "CI failed"

    def test_configured_result_does_not_leak_to_other_tasks(self) -> None:
        executor = FakeStepExecutor()
        merged = StepResult(outcome=StepOutcome.ADVANCE, detail="merged")
        executor.set_result("task-001", "merge", merged)
        other_task = _make_task("task-002")

        result = executor.execute(other_task, "merge", {})

        assert result.outcome == StepOutcome.ADVANCE
        assert result.detail == "OK"

    def test_configured_result_does_not_leak_to_other_steps(self) -> None:
        executor = FakeStepExecutor()
        merged = StepResult(outcome=StepOutcome.ADVANCE, detail="merged")
        executor.set_result("task-001", "merge", merged)
        task = _make_task()

        result = executor.execute(task, "lint", {})

        assert result.outcome == StepOutcome.ADVANCE
        assert result.detail == "OK"


class TestStepExecutorRecordsExecutions:
    def test_records_all_executions(self) -> None:
        executor = FakeStepExecutor()
        task = _make_task()

        executor.execute(task, "merge", {"force": True})
        executor.execute(task, "lint", {})

        assert len(executor.executed) == 2
        assert executor.executed[0] == ("task-001", "merge", {"force": True})
        assert executor.executed[1] == ("task-001", "lint", {})

    def test_pr_url_in_result(self) -> None:
        executor = FakeStepExecutor()
        executor.set_result(
            "task-001",
            "create-pr",
            StepResult(
                outcome=StepOutcome.ADVANCE,
                detail="created",
                pr_url="https://github.com/org/repo/pull/1",
            ),
        )
        task = _make_task()

        result = executor.execute(task, "create-pr", {})

        assert result.pr_url == "https://github.com/org/repo/pull/1"


# ---------------------------------------------------------------------------
# FakeSignalPort contract tests
# ---------------------------------------------------------------------------


class TestSignalPortDefaultSignal:
    def test_returns_pending_by_default(self) -> None:
        port = FakeSignalPort()
        task = _make_task()

        signal = port.check(task, "human-approval", {})

        assert signal.status == SignalStatus.PENDING
        assert signal.message == ""

    def test_custom_default(self) -> None:
        port = FakeSignalPort()
        port.set_default(Signal(status=SignalStatus.APPROVED, message="auto"))
        task = _make_task()

        signal = port.check(task, "any-signal", {})

        assert signal.status == SignalStatus.APPROVED
        assert signal.message == "auto"


class TestSignalPortConfiguredSignal:
    def test_returns_configured_signal(self) -> None:
        port = FakeSignalPort()
        approved = Signal(status=SignalStatus.APPROVED, message="LGTM")
        port.set_signal("task-001", "human-approval", approved)
        task = _make_task()

        signal = port.check(task, "human-approval", {})

        assert signal.status == SignalStatus.APPROVED
        assert signal.message == "LGTM"

    def test_rejected_with_feedback(self) -> None:
        port = FakeSignalPort()
        rejected = Signal(status=SignalStatus.REJECTED, message="fix the null check")
        port.set_signal("task-001", "code-review", rejected)
        task = _make_task()

        signal = port.check(task, "code-review", {})

        assert signal.status == SignalStatus.REJECTED
        assert signal.message == "fix the null check"

    def test_configured_signal_does_not_leak_to_other_tasks(self) -> None:
        port = FakeSignalPort()
        port.set_signal("task-001", "review", Signal(status=SignalStatus.APPROVED, message="ok"))
        other_task = _make_task("task-002")

        signal = port.check(other_task, "review", {})

        assert signal.status == SignalStatus.PENDING


class TestSignalPortRecordsChecks:
    def test_records_all_checks(self) -> None:
        port = FakeSignalPort()
        task = _make_task()

        port.check(task, "human-approval", {"reviewers": ["alice"]})
        port.check(task, "ci-status", {})

        assert len(port.checked) == 2
        assert port.checked[0] == ("task-001", "human-approval", {"reviewers": ["alice"]})
        assert port.checked[1] == ("task-001", "ci-status", {})


# ---------------------------------------------------------------------------
# FakeChannelPort contract tests
# ---------------------------------------------------------------------------


class TestChannelPortGateBlocked:
    def test_records_gate_blocked(self) -> None:
        channel = FakeChannelPort()
        task = _make_task()

        channel.gate_blocked(task=task, signal_name="human-approval")

        assert len(channel.gate_blocked_calls) == 1
        assert channel.gate_blocked_calls[0] == ("task-001", "human-approval")


class TestChannelPortTaskErrored:
    def test_records_task_errored(self) -> None:
        channel = FakeChannelPort()
        task = _make_task()

        channel.task_errored(task=task, detail="max rounds exceeded")

        assert len(channel.task_errored_calls) == 1
        assert channel.task_errored_calls[0] == ("task-001", "max rounds exceeded")


class TestChannelPortWorkerCrashed:
    def test_records_worker_crashed(self) -> None:
        channel = FakeChannelPort()
        task = _make_task()

        channel.worker_crashed(task=task, role="implementer", branch="hyperloop/task-001")

        assert len(channel.worker_crashed_calls) == 1
        assert channel.worker_crashed_calls[0] == ("task-001", "implementer", "hyperloop/task-001")


class TestChannelPortMultipleCalls:
    def test_records_multiple_calls_independently(self) -> None:
        channel = FakeChannelPort()
        task1 = _make_task("task-001")
        task2 = _make_task("task-002")

        channel.gate_blocked(task=task1, signal_name="review")
        channel.task_errored(task=task2, detail="CI failed")
        channel.worker_crashed(task=task1, role="verifier", branch="hyperloop/task-001")

        assert len(channel.gate_blocked_calls) == 1
        assert len(channel.task_errored_calls) == 1
        assert len(channel.worker_crashed_calls) == 1


# ---------------------------------------------------------------------------
# RecordingProbe contract tests — new methods
# ---------------------------------------------------------------------------


class TestRecordingProbeNewMethods:
    def test_drift_detected(self) -> None:
        probe = RecordingProbe()
        probe.drift_detected(spec_path="specs/auth.md", drift_type="modified", detail="field added")

        calls = probe.of_method("drift_detected")
        assert len(calls) == 1
        assert calls[0]["spec_path"] == "specs/auth.md"
        assert calls[0]["drift_type"] == "modified"

    def test_audit_ran(self) -> None:
        probe = RecordingProbe()
        probe.audit_ran(spec_ref="specs/auth.md@abc", result="pass", cycle=1, duration_s=2.5)

        assert probe.last("audit_ran")["result"] == "pass"

    def test_gc_ran(self) -> None:
        probe = RecordingProbe()
        probe.gc_ran(pruned_count=3, cycle=5)

        assert probe.last("gc_ran")["pruned_count"] == 3

    def test_convergence_marked(self) -> None:
        probe = RecordingProbe()
        probe.convergence_marked(spec_path="specs/auth.md", spec_ref="specs/auth.md@abc", cycle=2)

        assert probe.last("convergence_marked")["spec_path"] == "specs/auth.md"

    def test_worker_crash_detected(self) -> None:
        probe = RecordingProbe()
        probe.worker_crash_detected(
            task_id="task-001", role="implementer", branch="hyperloop/task-001"
        )

        assert probe.last("worker_crash_detected")["task_id"] == "task-001"

    def test_step_executed(self) -> None:
        probe = RecordingProbe()
        probe.step_executed(
            task_id="task-001",
            step_name="merge",
            outcome="advance",
            detail="ok",
            cycle=3,
        )

        assert probe.last("step_executed")["step_name"] == "merge"
        assert probe.last("step_executed")["outcome"] == "advance"

    def test_signal_checked(self) -> None:
        probe = RecordingProbe()
        probe.signal_checked(
            task_id="task-001",
            signal_name="review",
            status="approved",
            message="LGTM",
            cycle=1,
        )

        assert probe.last("signal_checked")["signal_name"] == "review"
        assert probe.last("signal_checked")["status"] == "approved"

    def test_task_retried(self) -> None:
        probe = RecordingProbe()
        probe.task_retried(
            task_id="task-001",
            spec_ref="specs/x.md",
            round=2,
            cycle=3,
            findings_preview="failed",
        )

        assert probe.last("task_retried")["task_id"] == "task-001"


class TestRecordingProbeExistingMethods:
    def test_cycle_started_uses_completed_kwarg(self) -> None:
        probe = RecordingProbe()
        probe.cycle_started(
            cycle=1,
            active_workers=0,
            not_started=5,
            in_progress=0,
            completed=0,
            failed=0,
        )

        assert probe.last("cycle_started")["completed"] == 0

    def test_cycle_completed_uses_completed_kwarg(self) -> None:
        probe = RecordingProbe()
        probe.cycle_completed(
            cycle=1,
            active_workers=0,
            not_started=0,
            in_progress=0,
            completed=5,
            failed=0,
            spawned_ids=(),
            reaped_ids=(),
            duration_s=1.0,
        )

        assert probe.last("cycle_completed")["completed"] == 5

    def test_state_synced_no_args(self) -> None:
        probe = RecordingProbe()
        probe.state_synced()

        calls = probe.of_method("state_synced")
        assert len(calls) == 1
