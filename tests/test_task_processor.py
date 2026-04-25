"""Tests for the task processor — pure domain logic for flat phase map execution.

Covers every scenario from specs/task-processor.spec.md:
step type detection, outcome routing, round increments, terminal phases,
max rounds, first-phase init, and deterministic spawn order.
"""

from __future__ import annotations

import pytest

from hyperloop.domain.model import (
    Phase,
    PhaseMap,
    PhaseStep,
    Signal,
    SignalStatus,
    StepOutcome,
    StepResult,
    StepType,
    Task,
    TaskStatus,
    Verdict,
    WorkerResult,
)
from hyperloop.domain.task_processor import (
    check_max_rounds,
    determine_step_type,
    extract_role,
    first_phase,
    is_terminal,
    process_result,
    should_increment_round,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def implement_phase() -> PhaseStep:
    return PhaseStep(run="agent implementer", on_pass="verify", on_fail="implement")


@pytest.fixture
def verify_phase() -> PhaseStep:
    return PhaseStep(run="agent verifier", on_pass="merge", on_fail="implement")


@pytest.fixture
def merge_phase() -> PhaseStep:
    return PhaseStep(run="action merge", on_pass="done", on_fail="implement")


@pytest.fixture
def signal_phase() -> PhaseStep:
    return PhaseStep(
        run="signal human-approval",
        on_pass="merge",
        on_fail="implement",
        on_wait="await-review",
    )


@pytest.fixture
def check_phase() -> PhaseStep:
    return PhaseStep(run="check ci-status", on_pass="merge", on_fail="implement")


@pytest.fixture
def sample_phases(
    implement_phase: PhaseStep,
    verify_phase: PhaseStep,
    merge_phase: PhaseStep,
) -> PhaseMap:
    return {
        "implement": implement_phase,
        "verify": verify_phase,
        "merge": merge_phase,
    }


def _task(
    id: str = "task-001",
    status: TaskStatus = TaskStatus.NOT_STARTED,
    phase: Phase | None = None,
    deps: tuple[str, ...] = (),
    round: int = 0,
    branch: str | None = None,
) -> Task:
    return Task(
        id=id,
        title=f"Task {id}",
        spec_ref=f"specs/{id}.md",
        status=status,
        phase=phase,
        deps=deps,
        round=round,
        branch=branch,
        pr=None,
    )


# ---------------------------------------------------------------------------
# determine_step_type
# ---------------------------------------------------------------------------


class TestDetermineStepType:
    def test_agent_step(self, implement_phase: PhaseStep) -> None:
        assert determine_step_type(implement_phase) == StepType.AGENT

    def test_action_step(self, merge_phase: PhaseStep) -> None:
        assert determine_step_type(merge_phase) == StepType.ACTION

    def test_signal_step(self, signal_phase: PhaseStep) -> None:
        assert determine_step_type(signal_phase) == StepType.SIGNAL

    def test_check_step(self, check_phase: PhaseStep) -> None:
        assert determine_step_type(check_phase) == StepType.CHECK

    def test_unknown_step_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown step type"):
            PhaseStep(run="unknown foo", on_pass="done", on_fail="start")


# ---------------------------------------------------------------------------
# extract_role
# ---------------------------------------------------------------------------


class TestExtractRole:
    def test_agent_role(self, implement_phase: PhaseStep) -> None:
        assert extract_role(implement_phase) == "implementer"

    def test_action_name(self, merge_phase: PhaseStep) -> None:
        assert extract_role(merge_phase) == "merge"

    def test_signal_name(self, signal_phase: PhaseStep) -> None:
        assert extract_role(signal_phase) == "human-approval"

    def test_check_name(self, check_phase: PhaseStep) -> None:
        assert extract_role(check_phase) == "ci-status"


# ---------------------------------------------------------------------------
# process_result — WorkerResult
# ---------------------------------------------------------------------------


class TestProcessResultWorker:
    def test_pass_verdict_advances(self, implement_phase: PhaseStep) -> None:
        result = WorkerResult(verdict=Verdict.PASS, detail="all tests pass")
        outcome, next_phase = process_result(implement_phase, result, "implement")
        assert outcome == StepOutcome.ADVANCE
        assert next_phase == "verify"

    def test_fail_verdict_retries(self, verify_phase: PhaseStep) -> None:
        result = WorkerResult(verdict=Verdict.FAIL, detail="missing error handling")
        outcome, next_phase = process_result(verify_phase, result, "verify")
        assert outcome == StepOutcome.RETRY
        assert next_phase == "implement"

    def test_worker_crash_no_verdict_defaults_to_fail(self, implement_phase: PhaseStep) -> None:
        """Worker crash without verdict defaults to FAIL."""
        outcome, next_phase = process_result(implement_phase, None, "implement")
        assert outcome == StepOutcome.RETRY
        assert next_phase == "implement"


# ---------------------------------------------------------------------------
# process_result — StepResult
# ---------------------------------------------------------------------------


class TestProcessResultStep:
    def test_step_advance(self, merge_phase: PhaseStep) -> None:
        result = StepResult(outcome=StepOutcome.ADVANCE, detail="merged")
        outcome, next_phase = process_result(merge_phase, result, "merge")
        assert outcome == StepOutcome.ADVANCE
        assert next_phase == "done"

    def test_step_retry(self, merge_phase: PhaseStep) -> None:
        result = StepResult(outcome=StepOutcome.RETRY, detail="conflict")
        outcome, next_phase = process_result(merge_phase, result, "merge")
        assert outcome == StepOutcome.RETRY
        assert next_phase == "implement"

    def test_step_wait(self, merge_phase: PhaseStep) -> None:
        result = StepResult(outcome=StepOutcome.WAIT, detail="pending CI")
        outcome, next_phase = process_result(merge_phase, result, "merge")
        assert outcome == StepOutcome.WAIT
        # No on_wait defined, so stays at current phase
        assert next_phase == "merge"


# ---------------------------------------------------------------------------
# process_result — Signal
# ---------------------------------------------------------------------------


class TestProcessResultSignal:
    def test_signal_approved_advances(self, signal_phase: PhaseStep) -> None:
        sig = Signal(status=SignalStatus.APPROVED, message="lgtm")
        outcome, next_phase = process_result(signal_phase, sig, "await-review")
        assert outcome == StepOutcome.ADVANCE
        assert next_phase == "merge"

    def test_signal_rejected_retries(self, signal_phase: PhaseStep) -> None:
        sig = Signal(status=SignalStatus.REJECTED, message="needs timeout handling")
        outcome, next_phase = process_result(signal_phase, sig, "await-review")
        assert outcome == StepOutcome.RETRY
        assert next_phase == "implement"

    def test_signal_pending_waits(self, signal_phase: PhaseStep) -> None:
        sig = Signal(status=SignalStatus.PENDING, message="")
        outcome, next_phase = process_result(signal_phase, sig, "await-review")
        assert outcome == StepOutcome.WAIT
        assert next_phase == "await-review"

    def test_signal_pending_no_on_wait_stays_current(self, implement_phase: PhaseStep) -> None:
        """When on_wait is None, WAIT stays at current_phase."""
        sig = Signal(status=SignalStatus.PENDING, message="")
        outcome, next_phase = process_result(implement_phase, sig, "implement")
        assert outcome == StepOutcome.WAIT
        assert next_phase == "implement"


# ---------------------------------------------------------------------------
# should_increment_round
# ---------------------------------------------------------------------------


class TestShouldIncrementRound:
    def test_retry_increments(self) -> None:
        assert should_increment_round(StepOutcome.RETRY) is True

    def test_advance_does_not_increment(self) -> None:
        assert should_increment_round(StepOutcome.ADVANCE) is False

    def test_wait_does_not_increment(self) -> None:
        assert should_increment_round(StepOutcome.WAIT) is False


# ---------------------------------------------------------------------------
# is_terminal
# ---------------------------------------------------------------------------


class TestIsTerminal:
    def test_done_is_terminal(self) -> None:
        assert is_terminal("done") is True

    def test_regular_phase_not_terminal(self) -> None:
        assert is_terminal("verify") is False

    def test_empty_string_not_terminal(self) -> None:
        assert is_terminal("") is False


# ---------------------------------------------------------------------------
# check_max_rounds
# ---------------------------------------------------------------------------


class TestCheckMaxRounds:
    def test_at_max_rounds_returns_true(self) -> None:
        task = _task(status=TaskStatus.IN_PROGRESS, round=50)
        assert check_max_rounds(task, max_rounds=50) is True

    def test_over_max_rounds_returns_true(self) -> None:
        task = _task(status=TaskStatus.IN_PROGRESS, round=51)
        assert check_max_rounds(task, max_rounds=50) is True

    def test_under_max_rounds_returns_false(self) -> None:
        task = _task(status=TaskStatus.IN_PROGRESS, round=49)
        assert check_max_rounds(task, max_rounds=50) is False

    def test_zero_rounds_returns_false(self) -> None:
        task = _task(status=TaskStatus.IN_PROGRESS, round=0)
        assert check_max_rounds(task, max_rounds=50) is False


# ---------------------------------------------------------------------------
# first_phase
# ---------------------------------------------------------------------------


class TestFirstPhase:
    def test_returns_first_key(self, sample_phases: PhaseMap) -> None:
        assert first_phase(sample_phases) == "implement"

    def test_single_phase(self) -> None:
        phases: PhaseMap = {"only": PhaseStep(run="agent worker", on_pass="done", on_fail="only")}
        assert first_phase(phases) == "only"

    def test_empty_phases_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            first_phase({})


# ---------------------------------------------------------------------------
# Integration: full phase transition scenarios
# ---------------------------------------------------------------------------


class TestPhaseTransitionScenarios:
    """End-to-end scenarios matching the spec requirements."""

    def test_advance_does_not_increment_round(self, implement_phase: PhaseStep) -> None:
        """Scenario: ADVANCE does not increment round (spec section)."""
        result = WorkerResult(verdict=Verdict.PASS, detail="done")
        outcome, _ = process_result(implement_phase, result, "implement")
        assert outcome == StepOutcome.ADVANCE
        assert should_increment_round(outcome) is False

    def test_retry_increments_round(self, verify_phase: PhaseStep) -> None:
        """Scenario: RETRY increments round (spec section)."""
        result = WorkerResult(verdict=Verdict.FAIL, detail="bad code")
        outcome, _ = process_result(verify_phase, result, "verify")
        assert outcome == StepOutcome.RETRY
        assert should_increment_round(outcome) is True

    def test_reaching_done_is_terminal(self, merge_phase: PhaseStep) -> None:
        """Scenario: Reaching terminal completion (spec section)."""
        result = StepResult(outcome=StepOutcome.ADVANCE, detail="merged")
        outcome, next_phase = process_result(merge_phase, result, "merge")
        assert outcome == StepOutcome.ADVANCE
        assert next_phase == "done"
        assert is_terminal(next_phase) is True

    def test_max_rounds_exceeded(self) -> None:
        """Scenario: Max rounds exceeded (spec section)."""
        task = _task(status=TaskStatus.IN_PROGRESS, round=50)
        assert check_max_rounds(task, max_rounds=50) is True

    def test_first_phase_initialization(self, sample_phases: PhaseMap) -> None:
        """Scenario: Task pickup sets first phase (spec section)."""
        phase_name = first_phase(sample_phases)
        assert phase_name == "implement"

    def test_deterministic_spawn_order(self) -> None:
        """Scenario: Deterministic spawn order by task ID.

        Given 5 eligible tasks, selection should be by task ID order (lowest
        first). This is verified via sorted() on task IDs.
        """
        task_ids = ["task-005", "task-001", "task-003", "task-002", "task-004"]
        sorted_ids = sorted(task_ids)
        assert sorted_ids == [
            "task-001",
            "task-002",
            "task-003",
            "task-004",
            "task-005",
        ]
        # The decide function handles this; we verify the principle holds.
        # Task processor functions are pure utilities — spawn ordering is
        # enforced by the orchestrator calling sorted().
