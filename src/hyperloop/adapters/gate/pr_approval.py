"""PRApprovalGate -- checks for GitHub PR review approvals."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperloop.domain.model import Task
    from hyperloop.ports.pr import PRPort


class PRApprovalGate:
    """GatePort adapter that checks for GitHub PR review approvals."""

    def __init__(
        self,
        pr: PRPort,
        reviewers: tuple[str, ...] = (),
        repo: str = "",
    ) -> None:
        self._pr = pr
        self._reviewers = reviewers
        self._repo = repo
        self._requested: set[str] = set()  # track which PRs have had reviews requested

    def check(self, task: Task, gate_name: str) -> bool:
        """Return True if the gate is cleared for this task.

        Handles PR state: if MERGED, returns True. If CLOSED, returns False.
        On first check, requests reviews from configured reviewers.
        """
        if task.pr is None:
            return False

        # Check PR state
        pr_state = self._pr.get_pr_state(task.pr)
        if pr_state is not None:
            if pr_state.state == "MERGED":
                return True
            if pr_state.state == "CLOSED":
                return False

        # Request reviews on first check (idempotent via _requested tracking)
        if task.pr not in self._requested and self._reviewers:
            self._request_reviews(task.pr)
            self._requested.add(task.pr)

        # Check review decision via gh CLI
        return self._check_approval(task.pr)

    def _request_reviews(self, pr_url: str) -> None:
        """Request reviews from configured reviewers."""
        for reviewer in self._reviewers:
            subprocess.run(
                ["gh", "pr", "edit", pr_url, "--add-reviewer", reviewer, "--repo", self._repo],
                capture_output=True,
                text=True,
            )

    def _check_approval(self, pr_url: str) -> bool:
        """Check if the PR has an approving review."""
        result = subprocess.run(
            ["gh", "pr", "view", pr_url, "--json", "reviewDecision", "--repo", self._repo],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False
        data = json.loads(result.stdout)
        return str(data.get("reviewDecision", "")) == "APPROVED"
