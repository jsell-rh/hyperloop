"""GitHubCommentChannel -- posts notifications as GitHub PR comments."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class GitHubCommentChannel:
    """ChannelPort adapter that posts GitHub PR comments."""

    def __init__(self, repo: str) -> None:
        self._repo = repo
        self._commented: set[str] = set()

    def gate_blocked(self, *, task: Task, signal_name: str) -> None:
        """A task is waiting for human action at a signal."""
        if task.pr is None or task.pr in self._commented:
            return

        if signal_name == "pr-require-label":
            body = (
                "## Hyperloop: Approval Required\n\n"
                "This PR was created by hyperloop and requires human approval before merge.\n\n"
                "**Action required:** Add the `lgtm` label to approve this PR.\n\n"
                "Once the label is added, hyperloop will automatically merge this PR."
            )
        elif signal_name == "pr-require-approval":
            body = (
                "## Hyperloop: Review Required\n\n"
                "This PR was created by hyperloop and requires a review approval before merge.\n\n"
                "**Action required:** Review and approve this PR.\n\n"
                "Once approved, hyperloop will automatically merge this PR."
            )
        else:
            body = (
                f"## Hyperloop: Signal Blocked\n\n"
                f"This PR is waiting on signal `{signal_name}` before it can proceed.\n"
            )

        self._post_comment(task.pr, body)
        self._commented.add(task.pr)

    def task_errored(self, *, task: Task, detail: str) -> None:
        """A task hit errors and needs investigation."""
        if task.pr is None:
            return
        body = (
            f"## Hyperloop: Action Failed\n\n"
            f"**Detail:** {detail}\n\n"
            f"The task has been sent back to the implementer for resolution."
        )
        self._post_comment(task.pr, body)

    def worker_crashed(self, *, task: Task, role: str, branch: str) -> None:
        """A worker crashed for this task."""
        if task.pr is None:
            return
        body = (
            f"## Hyperloop: Worker Crashed\n\n"
            f"Worker `{role}` crashed on branch `{branch}`.\n\n"
            f"The orchestrator will handle recovery."
        )
        self._post_comment(task.pr, body)

    def _post_comment(self, pr_url: str, body: str) -> None:
        subprocess.run(
            ["gh", "pr", "comment", pr_url, "--body", body, "--repo", self._repo],
            capture_output=True,
            text=True,
        )
