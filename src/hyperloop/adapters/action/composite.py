"""CompositeAction — dispatches to action handlers by name."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hyperloop.ports.action import ActionOutcome, ActionResult

if TYPE_CHECKING:
    from hyperloop.adapters.action.pr_actions import MarkPRReadyAction, PostPRCommentAction
    from hyperloop.adapters.action.pr_merge import PRMergeAction
    from hyperloop.domain.model import Task


class CompositeAction:
    """ActionPort implementation that routes to the correct handler by action name."""

    def __init__(
        self,
        merge: PRMergeAction | None = None,
        mark_ready: MarkPRReadyAction | None = None,
        post_comment: PostPRCommentAction | None = None,
    ) -> None:
        self._merge = merge
        self._mark_ready = mark_ready
        self._post_comment = post_comment

    def execute(self, task: Task, action_name: str, args: dict[str, object]) -> ActionResult:
        if action_name == "merge-pr" and self._merge is not None:
            return self._merge.execute(task, action_name, args)

        if action_name == "mark-pr-ready" and self._mark_ready is not None:
            return self._mark_ready.execute(task)

        if action_name == "post-pr-comment" and self._post_comment is not None:
            body = args.get("body")
            if not isinstance(body, str) or not body:
                return ActionResult(
                    outcome=ActionOutcome.ERROR,
                    detail="post-pr-comment requires 'body' in args",
                )
            return self._post_comment.execute(task, body)

        return ActionResult(
            outcome=ActionOutcome.ERROR,
            detail=f"Unknown action: {action_name}",
        )
