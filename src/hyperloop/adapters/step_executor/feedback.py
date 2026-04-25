"""FeedbackStep — checks for unprocessed PR comments and returns them as worker context."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from hyperloop.domain.model import StepOutcome, StepResult

if TYPE_CHECKING:
    from hyperloop.domain.model import Task
    from hyperloop.ports.feedback import FeedbackPort


class FeedbackStep:
    """StepExecutor handler for the 'feedback' action.

    Queries the FeedbackPort for unprocessed comments, marks them as processed,
    and returns RETRY with the feedback detail so the worker can address it.
    Returns ADVANCE when there is no unprocessed feedback.
    """

    def __init__(self, feedback: FeedbackPort) -> None:
        self._feedback = feedback

    def execute(self, task: Task, step_name: str, args: dict[str, object]) -> StepResult:
        if task.pr is None:
            return StepResult(outcome=StepOutcome.ADVANCE, detail="No unprocessed feedback")

        allowed_authors = cast("list[str]", args.get("allowed_authors", []))
        processed_emoji = str(args.get("processed_emoji", "eyes"))

        unprocessed = self._feedback.get_unprocessed(task, allowed_authors, processed_emoji)

        if not unprocessed:
            return StepResult(outcome=StepOutcome.ADVANCE, detail="No unprocessed feedback")

        comment_ids = [c.id for c in unprocessed]
        self._feedback.mark_processed(task, comment_ids, processed_emoji)

        feedback_text = "\n\n".join(f"**{c.author}** ({c.url}):\n{c.body}" for c in unprocessed)
        detail = f"Unprocessed feedback from {len(unprocessed)} comment(s):\n\n{feedback_text}"

        return StepResult(outcome=StepOutcome.RETRY, detail=detail)
