"""PRReviewCheck — agent-backed PR review evaluation with CI pre-checks."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, cast

from hyperloop.ports.check import CheckResult

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class PRReviewCheck:
    """CheckPort adapter for pr-review.

    Pre-conditions (mechanical, no agent needed):
    - CI checks must pass → WAIT if pending, FAIL if failed
    - Required reviewers must have posted → WAIT if not yet

    When pre-conditions are met → PASS, signaling the framework to spawn
    the check's agent for evaluation. The agent reads the PR feedback,
    assesses whether comments are valid/applicable/addressed, and writes
    a verdict.
    """

    def __init__(self, repo: str) -> None:
        self._repo = repo

    def evaluate(self, task: Task, check_name: str, args: dict[str, object]) -> CheckResult:
        if check_name != "pr-review":
            return CheckResult.PASS

        if task.pr is None:
            return CheckResult.PASS

        ci_result = self._check_ci(task.pr)
        if ci_result != CheckResult.PASS:
            return ci_result

        raw_reviewers = args.get("require_reviewers")
        if isinstance(raw_reviewers, list):
            reviewer_list = cast("list[str]", raw_reviewers)
            if not self._all_reviewers_posted(task.pr, reviewer_list):
                return CheckResult.WAIT

        return CheckResult.PASS

    def _check_ci(self, pr_url: str) -> CheckResult:
        """Check CI status on the PR. WAIT if pending, FAIL if failed, PASS if all green."""
        result = subprocess.run(
            [
                "gh",
                "pr",
                "checks",
                pr_url,
                "--json",
                "name,state,conclusion",
                "--repo",
                self._repo,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return CheckResult.WAIT

        try:
            checks = json.loads(result.stdout)
        except json.JSONDecodeError:
            return CheckResult.WAIT

        if not checks:
            return CheckResult.WAIT

        for check in checks:
            state = check.get("state", "")
            conclusion = check.get("conclusion", "")
            if state in ("PENDING", "QUEUED", "IN_PROGRESS", "WAITING"):
                return CheckResult.WAIT
            if conclusion in ("FAILURE", "TIMED_OUT", "CANCELLED"):
                return CheckResult.FAIL

        return CheckResult.PASS

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
