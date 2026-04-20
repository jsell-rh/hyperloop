"""Tests for new adapter implementations: LabelGate, PRMergeAction,
ProcessImproverHook, NullNotification.

Uses fakes exclusively -- no mocks, no subprocess calls.
"""

from __future__ import annotations

from hyperloop.adapters.action.pr_merge import PRMergeAction
from hyperloop.adapters.gate.label import LabelGate
from hyperloop.adapters.hook.process_improver import ProcessImproverHook
from hyperloop.adapters.notification.null import NullNotification
from hyperloop.compose import AgentTemplate, PromptComposer
from hyperloop.domain.model import (
    Task,
    TaskStatus,
    Verdict,
    WorkerResult,
)
from hyperloop.ports.action import ActionOutcome
from tests.fakes.pr import FakePRManager
from tests.fakes.probe import RecordingProbe
from tests.fakes.runtime import InMemoryRuntime
from tests.fakes.state import InMemoryStateStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task(
    task_id: str = "task-001",
    title: str = "Implement widget",
    spec_ref: str = "specs/widget.md",
    branch: str | None = "hyperloop/task-001",
    pr: str | None = None,
) -> Task:
    return Task(
        id=task_id,
        title=title,
        spec_ref=spec_ref,
        status=TaskStatus.IN_PROGRESS,
        phase=None,
        deps=(),
        round=1,
        branch=branch,
        pr=pr,
    )


def _pr_manager() -> FakePRManager:
    return FakePRManager(repo="org/repo")


def _composer(state: InMemoryStateStore) -> PromptComposer:
    """Build a minimal PromptComposer with a process-improver template."""
    templates = {
        "process-improver": AgentTemplate(
            name="process-improver",
            prompt="You are the process-improver.",
            guidelines="Improve the process.",
            annotations={},
        ),
    }
    return PromptComposer(templates=templates, state=state)


# ---------------------------------------------------------------------------
# LabelGate tests
# ---------------------------------------------------------------------------


class TestLabelGate:
    def test_check_returns_true_when_lgtm_label_present(self) -> None:
        pr = _pr_manager()
        gate = LabelGate(pr)
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr.add_label(pr_url, "lgtm")

        task = _task(pr=pr_url)
        assert gate.check(task, "lgtm") is True

    def test_check_returns_false_when_no_label(self) -> None:
        pr = _pr_manager()
        gate = LabelGate(pr)
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")

        task = _task(pr=pr_url)
        assert gate.check(task, "lgtm") is False

    def test_check_returns_true_when_pr_merged(self) -> None:
        pr = _pr_manager()
        gate = LabelGate(pr)
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        # Merge the PR via the fake
        pr.merge(pr_url, "task-001", "specs/widget.md")

        task = _task(pr=pr_url)
        # MERGED PR -> gate returns True regardless of label
        assert gate.check(task, "lgtm") is True

    def test_check_returns_false_when_pr_closed(self) -> None:
        pr = _pr_manager()
        gate = LabelGate(pr)
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr.close_pr(pr_url)

        task = _task(pr=pr_url)
        assert gate.check(task, "lgtm") is False

    def test_check_returns_false_when_no_pr(self) -> None:
        pr = _pr_manager()
        gate = LabelGate(pr)

        task = _task(pr=None)
        assert gate.check(task, "lgtm") is False


# ---------------------------------------------------------------------------
# PRMergeAction tests
# ---------------------------------------------------------------------------


class TestPRMergeAction:
    def test_successful_merge_returns_success(self) -> None:
        pr = _pr_manager()
        action = PRMergeAction(pr=pr, base_branch="main")
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")

        task = _task(pr=pr_url)
        result = action.execute(task, "merge-pr")

        assert result.outcome == ActionOutcome.SUCCESS
        assert pr_url in pr.merged

    def test_merge_conflict_returns_error(self) -> None:
        pr = _pr_manager()
        action = PRMergeAction(pr=pr, base_branch="main")
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr.set_rebase_fails("hyperloop/task-001")

        task = _task(pr=pr_url)
        result = action.execute(task, "merge-pr")

        assert result.outcome == ActionOutcome.ERROR
        assert "Rebase conflict" in result.detail

    def test_closed_pr_recreated(self) -> None:
        pr = _pr_manager()
        action = PRMergeAction(pr=pr, base_branch="main")
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr.close_pr(pr_url)

        task = _task(pr=pr_url)
        result = action.execute(task, "merge-pr")

        # Should succeed with a new PR URL
        assert result.outcome == ActionOutcome.SUCCESS
        assert result.pr_url is not None
        assert result.pr_url != pr_url

    def test_no_branch_returns_error(self) -> None:
        pr = _pr_manager()
        action = PRMergeAction(pr=pr, base_branch="main")

        task = _task(branch=None)
        result = action.execute(task, "merge-pr")

        assert result.outcome == ActionOutcome.ERROR
        assert "no branch" in result.detail.lower()

    def test_unknown_action_returns_error(self) -> None:
        pr = _pr_manager()
        action = PRMergeAction(pr=pr, base_branch="main")
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")

        task = _task(pr=pr_url)
        result = action.execute(task, "deploy")

        assert result.outcome == ActionOutcome.ERROR
        assert "Unknown action" in result.detail

    def test_no_pr_creates_one(self) -> None:
        pr = _pr_manager()
        action = PRMergeAction(pr=pr, base_branch="main")

        task = _task(pr=None)
        result = action.execute(task, "merge-pr")

        assert result.outcome == ActionOutcome.SUCCESS
        assert result.pr_url is not None

    def test_merge_failure_returns_error(self) -> None:
        pr = _pr_manager()
        action = PRMergeAction(pr=pr, base_branch="main")
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr.set_merge_fails(pr_url)

        task = _task(pr=pr_url)
        result = action.execute(task, "merge-pr")

        assert result.outcome == ActionOutcome.ERROR


# ---------------------------------------------------------------------------
# ProcessImproverHook tests
# ---------------------------------------------------------------------------


class TestProcessImproverHook:
    def test_after_reap_skips_when_no_failures(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = _composer(state)

        hook = ProcessImproverHook(runtime=runtime, composer=composer, probe=probe)
        results: dict[str, WorkerResult] = {
            "task-001": WorkerResult(verdict=Verdict.PASS, detail="All good"),
            "task-002": WorkerResult(verdict=Verdict.PASS, detail="Also good"),
        }

        hook.after_reap(results=results, cycle=1)

        # No serial run should have been triggered
        assert len(runtime.serial_runs) == 0

    def test_after_reap_runs_on_failures(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = _composer(state)

        hook = ProcessImproverHook(runtime=runtime, composer=composer, probe=probe)
        results: dict[str, WorkerResult] = {
            "task-001": WorkerResult(verdict=Verdict.FAIL, detail="Missing null check"),
            "task-002": WorkerResult(verdict=Verdict.PASS, detail="All good"),
        }

        hook.after_reap(results=results, cycle=3)

        # Serial run should have been triggered
        assert len(runtime.serial_runs) == 1
        assert runtime.serial_runs[0].role == "process-improver"
        assert "Missing null check" in runtime.serial_runs[0].prompt

    def test_after_reap_includes_all_failure_findings(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = _composer(state)

        hook = ProcessImproverHook(runtime=runtime, composer=composer, probe=probe)
        results: dict[str, WorkerResult] = {
            "task-001": WorkerResult(verdict=Verdict.FAIL, detail="Bug in parser"),
            "task-002": WorkerResult(verdict=Verdict.FAIL, detail="Timeout in API"),
            "task-003": WorkerResult(verdict=Verdict.PASS, detail="Fine"),
        }

        hook.after_reap(results=results, cycle=1)

        prompt = runtime.serial_runs[0].prompt
        assert "task-001" in prompt
        assert "Bug in parser" in prompt
        assert "task-002" in prompt
        assert "Timeout in API" in prompt
        # task-003 passed, should not appear in findings section
        assert "Fine" not in prompt

    def test_after_reap_emits_probe_event(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = _composer(state)

        hook = ProcessImproverHook(runtime=runtime, composer=composer, probe=probe)
        results: dict[str, WorkerResult] = {
            "task-001": WorkerResult(verdict=Verdict.FAIL, detail="Broken"),
        }

        hook.after_reap(results=results, cycle=5)

        pi_events = probe.of_method("process_improver_ran")
        assert len(pi_events) == 1
        assert pi_events[0]["cycle"] == 5
        assert pi_events[0]["success"] is True


# ---------------------------------------------------------------------------
# NullNotification tests
# ---------------------------------------------------------------------------


class TestNullNotification:
    def test_gate_blocked_does_nothing(self) -> None:
        notif = NullNotification()
        task = _task()
        # Should not raise
        notif.gate_blocked(task=task, gate_name="lgtm")

    def test_task_errored_does_nothing(self) -> None:
        notif = NullNotification()
        task = _task()
        # Should not raise
        notif.task_errored(task=task, attempts=3, detail="Too many errors")
