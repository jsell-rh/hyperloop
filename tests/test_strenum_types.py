"""Tests for StrEnum types — verify values, string compatibility, and membership.

All domain enums should be StrEnum so they work as strings in comparisons,
serialization, and probe/port interfaces without explicit .value access.
"""

from enum import StrEnum

from hyperloop.domain.model import (
    AuditResult,
    DriftType,
    PMFailureResponse,
    PromptLabel,
    PromptSource,
    SignalStatus,
    SpecChangeType,
    StepOutcome,
    StepType,
    TaskStatus,
    Verdict,
    WorkerPollStatus,
)

# ---------------------------------------------------------------------------
# All enums are StrEnum
# ---------------------------------------------------------------------------


class TestAllAreStrEnum:
    def test_task_status_is_strenum(self) -> None:
        assert issubclass(TaskStatus, StrEnum)

    def test_verdict_is_strenum(self) -> None:
        assert issubclass(Verdict, StrEnum)

    def test_step_outcome_is_strenum(self) -> None:
        assert issubclass(StepOutcome, StrEnum)

    def test_signal_status_is_strenum(self) -> None:
        assert issubclass(SignalStatus, StrEnum)

    def test_worker_poll_status_is_strenum(self) -> None:
        assert issubclass(WorkerPollStatus, StrEnum)

    def test_drift_type_is_strenum(self) -> None:
        assert issubclass(DriftType, StrEnum)

    def test_prompt_source_is_strenum(self) -> None:
        assert issubclass(PromptSource, StrEnum)

    def test_prompt_label_is_strenum(self) -> None:
        assert issubclass(PromptLabel, StrEnum)

    def test_spec_change_type_is_strenum(self) -> None:
        assert issubclass(SpecChangeType, StrEnum)

    def test_pm_failure_response_is_strenum(self) -> None:
        assert issubclass(PMFailureResponse, StrEnum)

    def test_audit_result_is_strenum(self) -> None:
        assert issubclass(AuditResult, StrEnum)

    def test_step_type_is_strenum(self) -> None:
        assert issubclass(StepType, StrEnum)


# ---------------------------------------------------------------------------
# String comparison compatibility
# ---------------------------------------------------------------------------


class TestStringComparison:
    """StrEnum values must compare equal to their string values."""

    def test_task_status_string_comparison(self) -> None:
        assert TaskStatus.NOT_STARTED == "not_started"
        assert TaskStatus.IN_PROGRESS == "in_progress"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.FAILED == "failed"

    def test_verdict_string_comparison(self) -> None:
        assert Verdict.PASS == "pass"
        assert Verdict.FAIL == "fail"

    def test_step_outcome_string_comparison(self) -> None:
        assert StepOutcome.ADVANCE == "advance"
        assert StepOutcome.RETRY == "retry"
        assert StepOutcome.WAIT == "wait"

    def test_signal_status_string_comparison(self) -> None:
        assert SignalStatus.APPROVED == "approved"
        assert SignalStatus.REJECTED == "rejected"
        assert SignalStatus.PENDING == "pending"

    def test_worker_poll_status_string_comparison(self) -> None:
        assert WorkerPollStatus.RUNNING == "running"
        assert WorkerPollStatus.DONE == "done"
        assert WorkerPollStatus.FAILED == "failed"

    def test_drift_type_string_comparison(self) -> None:
        assert DriftType.COVERAGE == "coverage"
        assert DriftType.FRESHNESS == "freshness"
        assert DriftType.ALIGNMENT == "alignment"

    def test_prompt_source_string_comparison(self) -> None:
        assert PromptSource.BASE == "base"
        assert PromptSource.PROJECT_OVERLAY == "project-overlay"
        assert PromptSource.PROCESS_OVERLAY == "process-overlay"
        assert PromptSource.SPEC == "spec"
        assert PromptSource.FINDINGS == "findings"
        assert PromptSource.RUNTIME == "runtime"
        assert PromptSource.PR == "pr"

    def test_prompt_label_string_comparison(self) -> None:
        assert PromptLabel.PROMPT == "prompt"
        assert PromptLabel.GUIDELINES == "guidelines"
        assert PromptLabel.SPEC == "spec"
        assert PromptLabel.FINDINGS == "findings"
        assert PromptLabel.EPILOGUE == "epilogue"
        assert PromptLabel.PR_FEEDBACK == "pr-feedback"

    def test_spec_change_type_string_comparison(self) -> None:
        assert SpecChangeType.ADDED == "added"
        assert SpecChangeType.MODIFIED == "modified"
        assert SpecChangeType.DELETED == "deleted"
        assert SpecChangeType.NEW == "new"

    def test_pm_failure_response_string_comparison(self) -> None:
        assert PMFailureResponse.BACKOFF == "backoff"
        assert PMFailureResponse.HALT == "halt"

    def test_audit_result_string_comparison(self) -> None:
        assert AuditResult.ALIGNED == "aligned"
        assert AuditResult.MISALIGNED == "misaligned"

    def test_step_type_string_comparison(self) -> None:
        assert StepType.AGENT == "agent"
        assert StepType.ACTION == "action"
        assert StepType.SIGNAL == "signal"
        assert StepType.CHECK == "check"


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------


class TestMembership:
    def test_task_status_members(self) -> None:
        members = {s.name for s in TaskStatus}
        assert members == {"NOT_STARTED", "IN_PROGRESS", "COMPLETED", "FAILED"}

    def test_verdict_members(self) -> None:
        members = {v.name for v in Verdict}
        assert members == {"PASS", "FAIL"}

    def test_worker_poll_status_members(self) -> None:
        members = {s.name for s in WorkerPollStatus}
        assert members == {"RUNNING", "DONE", "FAILED"}

    def test_drift_type_members(self) -> None:
        members = {d.name for d in DriftType}
        assert members == {"COVERAGE", "FRESHNESS", "ALIGNMENT"}

    def test_step_type_members(self) -> None:
        members = {s.name for s in StepType}
        assert members == {"AGENT", "ACTION", "SIGNAL", "CHECK"}


# ---------------------------------------------------------------------------
# StrEnum values work in set/dict lookups
# ---------------------------------------------------------------------------


class TestSetAndDictLookups:
    def test_worker_poll_status_in_set(self) -> None:
        terminal = {WorkerPollStatus.DONE, WorkerPollStatus.FAILED}
        assert "done" in terminal
        assert "failed" in terminal
        assert "running" not in terminal

    def test_step_type_in_frozenset(self) -> None:
        valid = frozenset(StepType)
        assert "agent" in valid
        assert "action" in valid
        assert "signal" in valid
        assert "check" in valid
        assert "unknown" not in valid
