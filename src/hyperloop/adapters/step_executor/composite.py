"""CompositeStepExecutor -- routes step_name to the correct handler."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hyperloop.domain.model import StepOutcome, StepResult

if TYPE_CHECKING:
    from hyperloop.adapters.step_executor.pr_actions import MarkReadyStep, PostCommentStep
    from hyperloop.adapters.step_executor.pr_merge import PRMergeStep
    from hyperloop.adapters.step_executor.pr_review import PRReviewStep
    from hyperloop.domain.model import Task


class CompositeStepExecutor:
    """StepExecutor implementation that routes to the correct handler by step name."""

    def __init__(
        self,
        merge: PRMergeStep | None = None,
        mark_ready: MarkReadyStep | None = None,
        post_comment: PostCommentStep | None = None,
        pr_review: PRReviewStep | None = None,
    ) -> None:
        self._merge = merge
        self._mark_ready = mark_ready
        self._post_comment = post_comment
        self._pr_review = pr_review

    def execute(self, task: Task, step_name: str, args: dict[str, object]) -> StepResult:
        if step_name == "merge-pr" and self._merge is not None:
            return self._merge.execute(task, step_name, args)

        if step_name == "mark-pr-ready" and self._mark_ready is not None:
            return self._mark_ready.execute(task, step_name, args)

        if step_name == "post-pr-comment" and self._post_comment is not None:
            return self._post_comment.execute(task, step_name, args)

        if step_name == "pr-review" and self._pr_review is not None:
            return self._pr_review.execute(task, step_name, args)

        return StepResult(
            outcome=StepOutcome.RETRY,
            detail=f"Unknown step: {step_name}",
        )
