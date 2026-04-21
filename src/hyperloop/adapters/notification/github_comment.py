"""GitHubCommentNotification -- posts notifications as GitHub PR comments."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class GitHubCommentNotification:
    """NotificationPort adapter that posts GitHub PR comments."""

    def __init__(self, repo: str) -> None:
        self._repo = repo
        self._commented: set[str] = set()  # track which PRs have been commented on

    def gate_blocked(self, *, task: Task, gate_name: str) -> None:
        """A task is waiting for human action at a gate."""
        if task.pr is None or task.pr in self._commented:
            return

        if gate_name == "pr-require-label":
            body = (
                "## Hyperloop: Approval Required\n\n"
                "This PR was created by hyperloop and requires human approval before merge.\n\n"
                "**Action required:** Add the `lgtm` label to approve this PR.\n\n"
                "Once the label is added, hyperloop will automatically merge this PR."
            )
        elif gate_name == "pr-require-approval":
            body = (
                "## Hyperloop: Review Required\n\n"
                "This PR was created by hyperloop and requires a review approval before merge.\n\n"
                "**Action required:** Review and approve this PR.\n\n"
                "Once approved, hyperloop will automatically merge this PR."
            )
        else:
            body = (
                f"## Hyperloop: Gate Blocked\n\n"
                f"This PR is waiting on gate `{gate_name}` before it can proceed.\n"
            )

        self._post_comment(task.pr, body)
        self._commented.add(task.pr)

    def task_errored(self, *, task: Task, attempts: int, detail: str) -> None:
        """A task hit max errors and needs investigation."""
        if task.pr is None:
            return
        body = (
            f"## Hyperloop: Action Failed\n\n"
            f"The merge action failed after {attempts} attempts.\n\n"
            f"**Detail:** {detail}\n\n"
            f"The task has been sent back to the implementer for resolution."
        )
        self._post_comment(task.pr, body)

    def _post_comment(self, pr_url: str, body: str) -> None:
        """Post a comment on a PR via gh CLI."""
        subprocess.run(
            ["gh", "pr", "comment", pr_url, "--body", body, "--repo", self._repo],
            capture_output=True,
            text=True,
        )
