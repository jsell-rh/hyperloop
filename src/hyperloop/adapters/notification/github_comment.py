"""GitHubCommentNotification -- posts notifications as GitHub PR comments.

Stub implementation -- not yet wired.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class GitHubCommentNotification:
    """NotificationPort adapter that posts GitHub PR comments."""

    def gate_blocked(self, *, task: Task, gate_name: str) -> None:
        """A task is waiting for human action at a gate."""
        raise NotImplementedError

    def task_errored(self, *, task: Task, attempts: int, detail: str) -> None:
        """A task hit max errors and needs investigation."""
        raise NotImplementedError
