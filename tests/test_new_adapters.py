"""Tests for new adapter implementations: StepExecutor, SignalPort, ChannelPort.

Uses fakes exclusively -- no mocks, no subprocess calls.
"""

from __future__ import annotations

from hyperloop.adapters.channel.github_comment import GitHubCommentChannel
from hyperloop.adapters.channel.null import NullChannel
from hyperloop.adapters.hook.process_improver import ProcessImproverHook
from hyperloop.adapters.signal.label import LabelSignal
from hyperloop.adapters.step_executor.composite import CompositeStepExecutor
from hyperloop.adapters.step_executor.pr_actions import MarkReadyStep, PostCommentStep
from hyperloop.adapters.step_executor.pr_merge import PRMergeStep
from hyperloop.compose import AgentTemplate, PromptComposer
from hyperloop.domain.model import (
    SignalStatus,
    StepOutcome,
    Task,
    TaskStatus,
    Verdict,
    WorkerResult,
)
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
            guidelines=["Improve the process."],
            annotations={},
        ),
    }
    return PromptComposer(templates=templates, state=state)


# ---------------------------------------------------------------------------
# LabelSignal tests
# ---------------------------------------------------------------------------


class TestLabelSignal:
    def test_approved_when_lgtm_label_present(self) -> None:
        pr = _pr_manager()
        signal = LabelSignal(pr)
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr.add_label(pr_url, "lgtm")

        task = _task(pr=pr_url)
        result = signal.check(task, "pr-require-label", {})
        assert result.status == SignalStatus.APPROVED

    def test_pending_when_no_label(self) -> None:
        pr = _pr_manager()
        signal = LabelSignal(pr)
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")

        task = _task(pr=pr_url)
        result = signal.check(task, "pr-require-label", {})
        assert result.status == SignalStatus.PENDING

    def test_approved_when_pr_merged(self) -> None:
        pr = _pr_manager()
        signal = LabelSignal(pr)
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr.merge(pr_url, "task-001", "specs/widget.md")

        task = _task(pr=pr_url)
        result = signal.check(task, "pr-require-label", {})
        assert result.status == SignalStatus.APPROVED

    def test_rejected_when_pr_closed(self) -> None:
        pr = _pr_manager()
        signal = LabelSignal(pr)
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr.close_pr(pr_url)

        task = _task(pr=pr_url)
        result = signal.check(task, "pr-require-label", {})
        assert result.status == SignalStatus.REJECTED

    def test_pending_when_no_pr(self) -> None:
        pr = _pr_manager()
        signal = LabelSignal(pr)

        task = _task(pr=None)
        result = signal.check(task, "pr-require-label", {})
        assert result.status == SignalStatus.PENDING


# ---------------------------------------------------------------------------
# PRMergeStep tests
# ---------------------------------------------------------------------------


class TestPRMergeStep:
    def test_successful_merge_returns_advance(self) -> None:
        pr = _pr_manager()
        step = PRMergeStep(pr=pr, base_branch="main")
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")

        task = _task(pr=pr_url)
        result = step.execute(task, "merge-pr", {})

        assert result.outcome == StepOutcome.ADVANCE
        assert pr_url in pr.merged

    def test_merge_conflict_returns_retry(self) -> None:
        pr = _pr_manager()
        step = PRMergeStep(pr=pr, base_branch="main")
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr.set_merge_fails(pr_url)

        task = _task(pr=pr_url)
        result = step.execute(task, "merge-pr", {})

        assert result.outcome == StepOutcome.RETRY
        assert "not mergeable" in result.detail.lower()

    def test_closed_pr_recreated(self) -> None:
        pr = _pr_manager()
        step = PRMergeStep(pr=pr, base_branch="main")
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr.close_pr(pr_url)

        task = _task(pr=pr_url)
        result = step.execute(task, "merge-pr", {})

        assert result.outcome == StepOutcome.ADVANCE
        assert result.pr_url is not None
        assert result.pr_url != pr_url

    def test_no_branch_returns_retry(self) -> None:
        pr = _pr_manager()
        step = PRMergeStep(pr=pr, base_branch="main")

        task = _task(branch=None)
        result = step.execute(task, "merge-pr", {})

        assert result.outcome == StepOutcome.RETRY
        assert "no branch" in result.detail.lower()

    def test_no_pr_creates_one(self) -> None:
        pr = _pr_manager()
        step = PRMergeStep(pr=pr, base_branch="main")

        task = _task(pr=None)
        result = step.execute(task, "merge-pr", {})

        assert result.outcome == StepOutcome.ADVANCE
        assert result.pr_url is not None


# ---------------------------------------------------------------------------
# MarkReadyStep tests
# ---------------------------------------------------------------------------


class TestMarkReadyStep:
    def test_marks_pr_ready(self) -> None:
        pr = _pr_manager()
        step = MarkReadyStep(pr)
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")

        task = _task(pr=pr_url)
        result = step.execute(task, "mark-pr-ready", {})

        assert result.outcome == StepOutcome.ADVANCE
        assert not pr.is_draft(pr_url)

    def test_no_pr_returns_wait(self) -> None:
        pr = _pr_manager()
        step = MarkReadyStep(pr)

        task = _task(pr=None)
        result = step.execute(task, "mark-pr-ready", {})

        assert result.outcome == StepOutcome.WAIT


# ---------------------------------------------------------------------------
# PostCommentStep tests
# ---------------------------------------------------------------------------


class TestPostCommentStep:
    def test_no_pr_returns_wait(self) -> None:
        step = PostCommentStep(repo="org/repo")

        task = _task(pr=None)
        result = step.execute(task, "post-pr-comment", {"body": "hello"})

        assert result.outcome == StepOutcome.WAIT

    def test_no_body_returns_retry(self) -> None:
        step = PostCommentStep(repo="org/repo")
        pr = _pr_manager()
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")

        task = _task(pr=pr_url)
        result = step.execute(task, "post-pr-comment", {})

        assert result.outcome == StepOutcome.RETRY


# ---------------------------------------------------------------------------
# CompositeStepExecutor tests
# ---------------------------------------------------------------------------


class TestCompositeStepExecutor:
    def test_routes_merge_to_pr_merge_step(self) -> None:
        pr = _pr_manager()
        merge = PRMergeStep(pr=pr, base_branch="main")
        composite = CompositeStepExecutor(merge=merge)
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")

        task = _task(pr=pr_url)
        result = composite.execute(task, "merge-pr", {})

        assert result.outcome == StepOutcome.ADVANCE

    def test_routes_mark_ready(self) -> None:
        pr = _pr_manager()
        mark_ready = MarkReadyStep(pr)
        composite = CompositeStepExecutor(mark_ready=mark_ready)
        pr_url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")

        task = _task(pr=pr_url)
        result = composite.execute(task, "mark-pr-ready", {})

        assert result.outcome == StepOutcome.ADVANCE

    def test_unknown_step_returns_retry(self) -> None:
        composite = CompositeStepExecutor()

        task = _task()
        result = composite.execute(task, "unknown-step", {})

        assert result.outcome == StepOutcome.RETRY
        assert "unknown" in result.detail.lower()


# ---------------------------------------------------------------------------
# NullChannel tests
# ---------------------------------------------------------------------------


class TestNullChannel:
    def test_gate_blocked_does_nothing(self) -> None:
        ch = NullChannel()
        task = _task()
        ch.gate_blocked(task=task, signal_name="lgtm")

    def test_task_errored_does_nothing(self) -> None:
        ch = NullChannel()
        task = _task()
        ch.task_errored(task=task, detail="Too many errors")

    def test_worker_crashed_does_nothing(self) -> None:
        ch = NullChannel()
        task = _task()
        ch.worker_crashed(task=task, role="implementer", branch="hyperloop/task-001")


# ---------------------------------------------------------------------------
# GitHubCommentChannel tests
# ---------------------------------------------------------------------------


class TestGitHubCommentChannel:
    def test_gate_blocked_no_pr_is_noop(self) -> None:
        ch = GitHubCommentChannel(repo="org/repo")
        task = _task(pr=None)
        # Should not raise
        ch.gate_blocked(task=task, signal_name="lgtm")

    def test_task_errored_no_pr_is_noop(self) -> None:
        ch = GitHubCommentChannel(repo="org/repo")
        task = _task(pr=None)
        ch.task_errored(task=task, detail="merge failed")

    def test_worker_crashed_no_pr_is_noop(self) -> None:
        ch = GitHubCommentChannel(repo="org/repo")
        task = _task(pr=None)
        ch.worker_crashed(task=task, role="implementer", branch="hyperloop/task-001")


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
