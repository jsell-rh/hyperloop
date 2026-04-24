"""PR lifecycle step handlers -- mark-pr-ready and post-pr-comment."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from hyperloop.domain.model import StepOutcome, StepResult

if TYPE_CHECKING:
    from hyperloop.domain.model import Task
    from hyperloop.ports.pr import PRPort


class MarkReadyStep:
    """Mark a draft PR as ready for review."""

    def __init__(self, pr: PRPort) -> None:
        self._pr = pr

    def execute(self, task: Task, step_name: str, args: dict[str, object]) -> StepResult:
        if task.pr is None:
            return StepResult(outcome=StepOutcome.WAIT, detail="No PR to mark ready")
        self._pr.mark_ready(task.pr)
        return StepResult(outcome=StepOutcome.ADVANCE, detail="PR marked ready")


class PostCommentStep:
    """Post a comment on the task's PR."""

    def __init__(self, repo: str) -> None:
        self._repo = repo

    def execute(self, task: Task, step_name: str, args: dict[str, object]) -> StepResult:
        if task.pr is None:
            return StepResult(outcome=StepOutcome.WAIT, detail="No PR to comment on")
        body = args.get("body")
        if not isinstance(body, str) or not body:
            return StepResult(
                outcome=StepOutcome.RETRY,
                detail="post-pr-comment requires 'body' in args",
            )
        result = subprocess.run(
            ["gh", "pr", "comment", task.pr, "--body", body, "--repo", self._repo],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return StepResult(
                outcome=StepOutcome.RETRY,
                detail=f"Failed to post comment: {result.stderr.strip()}",
            )
        return StepResult(outcome=StepOutcome.ADVANCE, detail="Comment posted")
