"""PRApprovalSignal -- checks for GitHub PR review approvals.

Returns Signal with APPROVED/PENDING/REJECTED status.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from hyperloop.domain.model import Signal, SignalStatus

if TYPE_CHECKING:
    from hyperloop.domain.model import Task
    from hyperloop.ports.pr import PRPort


class PRApprovalSignal:
    """SignalPort adapter that checks for GitHub PR review approvals."""

    def __init__(
        self,
        pr: PRPort,
        reviewers: tuple[str, ...] = (),
        repo: str = "",
    ) -> None:
        self._pr = pr
        self._reviewers = reviewers
        self._repo = repo
        self._requested: set[str] = set()

    def check(self, task: Task, signal_name: str, args: dict[str, object]) -> Signal:
        """Check if the PR has review approval.

        Returns:
            APPROVED -- PR approved or already merged
            REJECTED -- PR is closed
            PENDING -- awaiting review approval
        """
        if task.pr is None:
            return Signal(status=SignalStatus.PENDING, message="No PR")

        pr_state = self._pr.get_pr_state(task.pr)
        if pr_state is not None:
            if pr_state.state == "MERGED":
                return Signal(status=SignalStatus.APPROVED, message="PR already merged")
            if pr_state.state == "CLOSED":
                return Signal(status=SignalStatus.REJECTED, message="PR is closed")

        if task.pr not in self._requested and self._reviewers:
            self._request_reviews(task.pr)
            self._requested.add(task.pr)

        if self._check_approval(task.pr):
            return Signal(status=SignalStatus.APPROVED, message="PR approved")

        return Signal(status=SignalStatus.PENDING, message="Awaiting review approval")

    def _request_reviews(self, pr_url: str) -> None:
        for reviewer in self._reviewers:
            subprocess.run(
                ["gh", "pr", "edit", pr_url, "--add-reviewer", reviewer, "--repo", self._repo],
                capture_output=True,
                text=True,
            )

    def _check_approval(self, pr_url: str) -> bool:
        result = subprocess.run(
            ["gh", "pr", "view", pr_url, "--json", "reviewDecision", "--repo", self._repo],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False
        data = json.loads(result.stdout)
        return str(data.get("reviewDecision", "")) == "APPROVED"
