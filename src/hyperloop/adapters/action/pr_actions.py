"""PR lifecycle actions — mark-pr-ready and post-pr-comment."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from hyperloop.ports.action import ActionOutcome, ActionResult

if TYPE_CHECKING:
    from hyperloop.domain.model import Task
    from hyperloop.ports.pr import PRPort


class MarkPRReadyAction:
    """Mark a draft PR as ready for review."""

    def __init__(self, pr: PRPort) -> None:
        self._pr = pr

    def execute(self, task: Task) -> ActionResult:
        if task.pr is None:
            return ActionResult(outcome=ActionOutcome.RETRY, detail="No PR to mark ready")
        self._pr.mark_ready(task.pr)
        return ActionResult(outcome=ActionOutcome.SUCCESS, detail="PR marked ready")


class PostPRCommentAction:
    """Post a comment on the task's PR."""

    def __init__(self, repo: str) -> None:
        self._repo = repo

    def execute(self, task: Task, body: str) -> ActionResult:
        if task.pr is None:
            return ActionResult(outcome=ActionOutcome.RETRY, detail="No PR to comment on")
        result = subprocess.run(
            ["gh", "pr", "comment", task.pr, "--body", body, "--repo", self._repo],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return ActionResult(
                outcome=ActionOutcome.RETRY,
                detail=f"Failed to post comment: {result.stderr.strip()}",
            )
        return ActionResult(outcome=ActionOutcome.SUCCESS, detail="Comment posted")
