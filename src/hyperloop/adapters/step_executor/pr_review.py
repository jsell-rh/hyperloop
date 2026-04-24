"""PRReviewStep -- agent-backed PR review evaluation with CI pre-checks."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, cast

from hyperloop.domain.model import StepOutcome, StepResult

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class PRReviewStep:
    """StepExecutor handler for pr-review.

    Pre-conditions (mechanical, no agent needed):
    - CI checks must pass: WAIT if pending, RETRY if failed
    - Required reviewers must have posted: WAIT if not yet

    When pre-conditions are met: ADVANCE, signaling the framework to spawn
    the check's agent for evaluation.
    """

    def __init__(self, repo: str) -> None:
        self._repo = repo

    def execute(self, task: Task, step_name: str, args: dict[str, object]) -> StepResult:
        if task.pr is None:
            return StepResult(outcome=StepOutcome.ADVANCE, detail="No PR to review")

        ci_result = self._check_ci(task.pr)
        if ci_result is not None:
            return ci_result

        raw_reviewers = args.get("require_reviewers")
        if isinstance(raw_reviewers, list):
            reviewer_list = cast("list[str]", raw_reviewers)
            if not self._all_reviewers_posted(task.pr, reviewer_list):
                return StepResult(outcome=StepOutcome.WAIT, detail="Waiting for reviewers")

        return StepResult(outcome=StepOutcome.ADVANCE, detail="Pre-conditions met")

    def _check_ci(self, pr_url: str) -> StepResult | None:
        """Check CI status. Returns StepResult if not passing, None if all green."""
        result = subprocess.run(
            ["gh", "pr", "checks", pr_url, "--json", "name,state", "--repo", self._repo],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None

        try:
            checks = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

        if not checks:
            return None

        for check in checks:
            state = check.get("state", "")
            if state in ("PENDING", "QUEUED", "IN_PROGRESS", "WAITING"):
                return StepResult(outcome=StepOutcome.WAIT, detail="CI checks pending")
            if state in ("FAILURE", "TIMED_OUT", "CANCELLED", "ERROR"):
                return StepResult(outcome=StepOutcome.RETRY, detail="CI checks failed")

        return None

    def _all_reviewers_posted(self, pr_url: str, required: list[str]) -> bool:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                pr_url,
                "--json",
                "comments,reviews",
                "--repo",
                self._repo,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False

        data = json.loads(result.stdout)
        posted: set[str] = set()

        for review in data.get("reviews", []):
            author = review.get("author", {}).get("login", "")
            if author:
                posted.add(author)

        for comment in data.get("comments", []):
            author = comment.get("author", {}).get("login", "")
            if author:
                posted.add(author)

        return all(r in posted for r in required)
