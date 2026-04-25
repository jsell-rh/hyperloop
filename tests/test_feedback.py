"""Tests for FeedbackStep — emoji-tracked PR comment processing."""

from __future__ import annotations

import pytest

from hyperloop.domain.model import (
    Phase,
    PRComment,
    StepOutcome,
    Task,
    TaskStatus,
)
from tests.fakes.feedback import FakeFeedbackPort


def _make_task(
    task_id: str = "task-1",
    pr: str | None = "https://github.com/owner/repo/pull/42",
) -> Task:
    return Task(
        id=task_id,
        title="Test task",
        spec_ref="specs/test.md@abc",
        status=TaskStatus.IN_PROGRESS,
        phase=Phase("feedback"),
        deps=(),
        round=1,
        branch="task-1",
        pr=pr,
    )


def _make_comment(
    comment_id: str = "c1",
    author: str = "reviewer",
    body: str = "Please fix the tests",
    url: str = "https://github.com/owner/repo/pull/42#comment-1",
) -> PRComment:
    return PRComment(id=comment_id, author=author, body=body, url=url)


@pytest.fixture
def feedback() -> FakeFeedbackPort:
    return FakeFeedbackPort()


class TestFeedbackStepNoComments:
    def test_no_comments_returns_advance(self, feedback: FakeFeedbackPort) -> None:
        from hyperloop.adapters.step_executor.feedback import FeedbackStep

        step = FeedbackStep(feedback=feedback)
        task = _make_task()
        result = step.execute(task, "feedback", {"allowed_authors": ["reviewer"]})

        assert result.outcome == StepOutcome.ADVANCE
        assert "No unprocessed feedback" in result.detail


class TestFeedbackStepUnprocessedComment:
    def test_unprocessed_from_allowed_author_returns_retry(
        self, feedback: FakeFeedbackPort
    ) -> None:
        from hyperloop.adapters.step_executor.feedback import FeedbackStep

        comment = _make_comment()
        feedback.add_comment("task-1", comment)

        step = FeedbackStep(feedback=feedback)
        task = _make_task()
        result = step.execute(task, "feedback", {"allowed_authors": ["reviewer"]})

        assert result.outcome == StepOutcome.RETRY
        assert "Please fix the tests" in result.detail
        assert "reviewer" in result.detail
        assert "1 comment(s)" in result.detail

    def test_marks_comments_as_processed(self, feedback: FakeFeedbackPort) -> None:
        from hyperloop.adapters.step_executor.feedback import FeedbackStep

        comment = _make_comment()
        feedback.add_comment("task-1", comment)

        step = FeedbackStep(feedback=feedback)
        task = _make_task()
        step.execute(task, "feedback", {"allowed_authors": ["reviewer"]})

        assert len(feedback.mark_processed_calls) == 1
        task_id, ids, emoji = feedback.mark_processed_calls[0]
        assert task_id == "task-1"
        assert ids == ["c1"]
        assert emoji == "eyes"


class TestFeedbackStepNonAllowedAuthor:
    def test_comment_from_non_allowed_author_is_ignored(self, feedback: FakeFeedbackPort) -> None:
        from hyperloop.adapters.step_executor.feedback import FeedbackStep

        comment = _make_comment(author="random-person")
        feedback.add_comment("task-1", comment)

        step = FeedbackStep(feedback=feedback)
        task = _make_task()
        result = step.execute(task, "feedback", {"allowed_authors": ["reviewer"]})

        assert result.outcome == StepOutcome.ADVANCE
        assert "No unprocessed feedback" in result.detail


class TestFeedbackStepProcessedComment:
    def test_previously_processed_comment_is_ignored(self, feedback: FakeFeedbackPort) -> None:
        from hyperloop.adapters.step_executor.feedback import FeedbackStep

        comment = _make_comment()
        feedback.add_comment("task-1", comment)
        feedback.mark_processed(_make_task(), ["c1"], "eyes")

        step = FeedbackStep(feedback=feedback)
        task = _make_task()
        result = step.execute(task, "feedback", {"allowed_authors": ["reviewer"]})

        assert result.outcome == StepOutcome.ADVANCE


class TestFeedbackStepMultipleComments:
    def test_multiple_unprocessed_all_included_and_marked(self, feedback: FakeFeedbackPort) -> None:
        from hyperloop.adapters.step_executor.feedback import FeedbackStep

        c1 = _make_comment(comment_id="c1", body="Fix bug A")
        c2 = _make_comment(comment_id="c2", body="Fix bug B", author="reviewer")
        feedback.add_comment("task-1", c1)
        feedback.add_comment("task-1", c2)

        step = FeedbackStep(feedback=feedback)
        task = _make_task()
        result = step.execute(task, "feedback", {"allowed_authors": ["reviewer"]})

        assert result.outcome == StepOutcome.RETRY
        assert "Fix bug A" in result.detail
        assert "Fix bug B" in result.detail
        assert "2 comment(s)" in result.detail

        assert len(feedback.mark_processed_calls) == 1
        _, ids, _ = feedback.mark_processed_calls[0]
        assert set(ids) == {"c1", "c2"}


class TestFeedbackStepMixedProcessedAndUnprocessed:
    def test_only_unprocessed_returned(self, feedback: FakeFeedbackPort) -> None:
        from hyperloop.adapters.step_executor.feedback import FeedbackStep

        c1 = _make_comment(comment_id="c1", body="Already seen")
        c2 = _make_comment(comment_id="c2", body="New feedback")
        feedback.add_comment("task-1", c1)
        feedback.add_comment("task-1", c2)
        feedback.mark_processed(_make_task(), ["c1"], "eyes")

        step = FeedbackStep(feedback=feedback)
        task = _make_task()
        result = step.execute(task, "feedback", {"allowed_authors": ["reviewer"]})

        assert result.outcome == StepOutcome.RETRY
        assert "New feedback" in result.detail
        assert "Already seen" not in result.detail
        assert "1 comment(s)" in result.detail

        _, ids, _ = feedback.mark_processed_calls[-1]
        assert ids == ["c2"]


class TestFeedbackStepNoPR:
    def test_task_with_no_pr_returns_advance(self, feedback: FakeFeedbackPort) -> None:
        from hyperloop.adapters.step_executor.feedback import FeedbackStep

        step = FeedbackStep(feedback=feedback)
        task = _make_task(pr=None)
        result = step.execute(task, "feedback", {"allowed_authors": ["reviewer"]})

        assert result.outcome == StepOutcome.ADVANCE
        assert len(feedback.get_unprocessed_calls) == 0


class TestFeedbackStepCustomEmoji:
    def test_custom_processed_emoji_is_forwarded(self, feedback: FakeFeedbackPort) -> None:
        from hyperloop.adapters.step_executor.feedback import FeedbackStep

        comment = _make_comment()
        feedback.add_comment("task-1", comment)

        step = FeedbackStep(feedback=feedback)
        task = _make_task()
        step.execute(
            task,
            "feedback",
            {"allowed_authors": ["reviewer"], "processed_emoji": "rocket"},
        )

        _, _, emoji = feedback.mark_processed_calls[0]
        assert emoji == "rocket"

        _, _authors, emoji_get = feedback.get_unprocessed_calls[0]
        assert emoji_get == "rocket"


class TestFeedbackStepDefaultArgs:
    def test_defaults_to_eyes_emoji_and_empty_authors(self, feedback: FakeFeedbackPort) -> None:
        from hyperloop.adapters.step_executor.feedback import FeedbackStep

        step = FeedbackStep(feedback=feedback)
        task = _make_task()
        result = step.execute(task, "feedback", {})

        assert result.outcome == StepOutcome.ADVANCE
        _, authors, emoji = feedback.get_unprocessed_calls[0]
        assert authors == []
        assert emoji == "eyes"
