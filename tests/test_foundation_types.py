"""Tests for reconciler foundation types — new domain model types and ports.

Covers: StepOutcome, StepResult, SignalStatus, Signal, PhaseStep, PhaseMap,
TaskStatus.COMPLETED, Process with phases, and new port protocols.
"""

import pytest

from hyperloop.domain.model import (
    PhaseStep,
    Process,
    Signal,
    SignalStatus,
    StepOutcome,
    StepResult,
    Task,
    TaskStatus,
)

# ---------------------------------------------------------------------------
# StepOutcome enum
# ---------------------------------------------------------------------------


class TestStepOutcome:
    def test_enum_values(self) -> None:
        assert StepOutcome.ADVANCE.value == "advance"
        assert StepOutcome.RETRY.value == "retry"
        assert StepOutcome.WAIT.value == "wait"

    def test_all_members(self) -> None:
        members = {m.name for m in StepOutcome}
        assert members == {"ADVANCE", "RETRY", "WAIT"}


# ---------------------------------------------------------------------------
# StepResult value object
# ---------------------------------------------------------------------------


class TestStepResult:
    def test_creation_minimal(self) -> None:
        result = StepResult(outcome=StepOutcome.ADVANCE, detail="merged")
        assert result.outcome == StepOutcome.ADVANCE
        assert result.detail == "merged"
        assert result.pr_url is None

    def test_creation_with_pr_url(self) -> None:
        result = StepResult(
            outcome=StepOutcome.WAIT,
            detail="waiting for CI",
            pr_url="https://github.com/org/repo/pull/99",
        )
        assert result.pr_url == "https://github.com/org/repo/pull/99"

    def test_frozen(self) -> None:
        result = StepResult(outcome=StepOutcome.RETRY, detail="flaky")
        with pytest.raises(AttributeError):
            result.detail = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SignalStatus enum
# ---------------------------------------------------------------------------


class TestSignalStatus:
    def test_enum_values(self) -> None:
        assert SignalStatus.APPROVED.value == "approved"
        assert SignalStatus.REJECTED.value == "rejected"
        assert SignalStatus.PENDING.value == "pending"

    def test_all_members(self) -> None:
        members = {m.name for m in SignalStatus}
        assert members == {"APPROVED", "REJECTED", "PENDING"}


# ---------------------------------------------------------------------------
# Signal value object
# ---------------------------------------------------------------------------


class TestSignal:
    def test_creation(self) -> None:
        sig = Signal(status=SignalStatus.APPROVED, message="LGTM")
        assert sig.status == SignalStatus.APPROVED
        assert sig.message == "LGTM"

    def test_frozen(self) -> None:
        sig = Signal(status=SignalStatus.PENDING, message="awaiting review")
        with pytest.raises(AttributeError):
            sig.status = SignalStatus.APPROVED  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PhaseStep value object
# ---------------------------------------------------------------------------


class TestPhaseStep:
    def test_creation_minimal(self) -> None:
        step = PhaseStep(
            run="agent implementer",
            on_pass="verify",
            on_fail="implement",
        )
        assert step.run == "agent implementer"
        assert step.on_pass == "verify"
        assert step.on_fail == "implement"
        assert step.on_wait is None
        assert step.args == {}

    def test_creation_with_all_fields(self) -> None:
        step = PhaseStep(
            run="signal human-approval",
            on_pass="merge",
            on_fail="implement",
            on_wait="await-approval",
            args={"timeout_hours": 24},
        )
        assert step.on_wait == "await-approval"
        assert step.args == {"timeout_hours": 24}

    def test_frozen(self) -> None:
        step = PhaseStep(run="action merge", on_pass="done", on_fail="implement")
        with pytest.raises(AttributeError):
            step.run = "action rebase"  # type: ignore[misc]

    def test_args_default_is_empty_dict(self) -> None:
        step1 = PhaseStep(run="agent a", on_pass="b", on_fail="c")
        step2 = PhaseStep(run="agent a", on_pass="b", on_fail="c")
        assert step1.args is not step2.args or step1.args == {}


# ---------------------------------------------------------------------------
# PhaseMap type alias
# ---------------------------------------------------------------------------


class TestPhaseMap:
    def test_phase_map_is_dict(self) -> None:
        from hyperloop.domain.model import PhaseMap

        phases: PhaseMap = {
            "implement": PhaseStep(
                run="agent implementer",
                on_pass="verify",
                on_fail="implement",
            ),
            "verify": PhaseStep(
                run="agent verifier",
                on_pass="merge",
                on_fail="implement",
            ),
            "merge": PhaseStep(
                run="action merge",
                on_pass="done",
                on_fail="implement",
            ),
        }
        assert len(phases) == 3
        assert "implement" in phases
        assert phases["verify"].on_pass == "merge"


# ---------------------------------------------------------------------------
# TaskStatus.COMPLETED
# ---------------------------------------------------------------------------


class TestTaskStatusCompleted:
    def test_completed_value(self) -> None:
        assert TaskStatus.COMPLETED.value == "completed"

    def test_completed_is_distinct_from_old_complete(self) -> None:
        assert TaskStatus.COMPLETED != TaskStatus.COMPLETE

    def test_completed_in_members(self) -> None:
        members = {m.name for m in TaskStatus}
        assert "COMPLETED" in members


# ---------------------------------------------------------------------------
# Process with phases
# ---------------------------------------------------------------------------


class TestProcessWithPhases:
    def test_creation_with_phases(self) -> None:
        phases = {
            "implement": PhaseStep(
                run="agent implementer",
                on_pass="verify",
                on_fail="implement",
            ),
            "verify": PhaseStep(
                run="agent verifier",
                on_pass="done",
                on_fail="implement",
            ),
        }
        process = Process(name="default", phases=phases)
        assert process.name == "default"
        assert process.phases == phases
        assert len(process.phases) == 2

    def test_backward_compat_pipeline_still_works(self) -> None:
        """Old-style Process with pipeline= should still construct."""
        from hyperloop.domain.model import AgentStep, LoopStep

        process = Process(
            name="legacy",
            pipeline=(
                LoopStep(steps=(AgentStep(agent="implementer", on_pass=None, on_fail=None),)),
            ),
        )
        assert process.name == "legacy"
        assert len(process.pipeline) == 1


# ---------------------------------------------------------------------------
# New port protocols — verify they are importable and structurally correct
# ---------------------------------------------------------------------------


class TestStepExecutorPort:
    def test_importable(self) -> None:
        from hyperloop.ports.step_executor import StepExecutor

        assert hasattr(StepExecutor, "execute")

    def test_protocol_signature(self) -> None:
        """A class implementing execute(task, step_name, args) satisfies the protocol."""
        from hyperloop.ports.step_executor import StepExecutor  # noqa: TC001

        class FakeExecutor:
            def execute(self, task: Task, step_name: str, args: dict[str, object]) -> StepResult:
                return StepResult(outcome=StepOutcome.ADVANCE, detail="ok")

        executor: StepExecutor = FakeExecutor()
        result = executor.execute(
            task=Task(
                id="t1",
                title="x",
                spec_ref="s",
                status=TaskStatus.NOT_STARTED,
                phase=None,
                deps=(),
                round=0,
                branch=None,
                pr=None,
            ),
            step_name="merge",
            args={},
        )
        assert result.outcome == StepOutcome.ADVANCE


class TestSignalPort:
    def test_importable(self) -> None:
        from hyperloop.ports.signal import SignalPort

        assert hasattr(SignalPort, "check")

    def test_protocol_signature(self) -> None:
        from hyperloop.ports.signal import SignalPort  # noqa: TC001

        class FakeSignal:
            def check(self, task: Task, signal_name: str, args: dict[str, object]) -> Signal:
                return Signal(status=SignalStatus.PENDING, message="waiting")

        port: SignalPort = FakeSignal()
        result = port.check(
            task=Task(
                id="t1",
                title="x",
                spec_ref="s",
                status=TaskStatus.NOT_STARTED,
                phase=None,
                deps=(),
                round=0,
                branch=None,
                pr=None,
            ),
            signal_name="human-approval",
            args={},
        )
        assert result.status == SignalStatus.PENDING


class TestChannelPort:
    def test_importable(self) -> None:
        from hyperloop.ports.channel import ChannelPort

        assert hasattr(ChannelPort, "gate_blocked")
        assert hasattr(ChannelPort, "task_errored")
        assert hasattr(ChannelPort, "worker_crashed")


# ---------------------------------------------------------------------------
# Updated probe protocol — verify new methods exist
# ---------------------------------------------------------------------------


class TestProbeNewMethods:
    def test_new_methods_exist(self) -> None:
        from hyperloop.ports.probe import OrchestratorProbe

        assert hasattr(OrchestratorProbe, "drift_detected")
        assert hasattr(OrchestratorProbe, "audit_ran")
        assert hasattr(OrchestratorProbe, "gc_ran")
        assert hasattr(OrchestratorProbe, "convergence_marked")
        assert hasattr(OrchestratorProbe, "worker_crash_detected")
        assert hasattr(OrchestratorProbe, "step_executed")
        assert hasattr(OrchestratorProbe, "signal_checked")

    def test_renamed_methods(self) -> None:
        from hyperloop.ports.probe import OrchestratorProbe

        assert hasattr(OrchestratorProbe, "signal_checked")
        assert hasattr(OrchestratorProbe, "task_retried")

    def test_removed_methods_gone(self) -> None:
        from hyperloop.ports.probe import OrchestratorProbe

        assert not hasattr(OrchestratorProbe, "rebase_conflict")
        assert not hasattr(OrchestratorProbe, "intake_specs_detected")
        assert not hasattr(OrchestratorProbe, "pr_label_changed")
        assert not hasattr(OrchestratorProbe, "branch_pushed")

    def test_old_gate_checked_gone(self) -> None:
        from hyperloop.ports.probe import OrchestratorProbe

        assert not hasattr(OrchestratorProbe, "gate_checked")

    def test_old_task_looped_back_gone(self) -> None:
        from hyperloop.ports.probe import OrchestratorProbe

        assert not hasattr(OrchestratorProbe, "task_looped_back")
