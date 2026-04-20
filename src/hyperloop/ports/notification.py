"""NotificationPort — interface for notifying humans.

Implementations: GitHubCommentNotification, NullNotification.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class NotificationPort(Protocol):
    """How humans are told to act."""

    def gate_blocked(self, *, task: Task, gate_name: str) -> None:
        """A task is waiting for human action at a gate."""
        ...

    def task_errored(self, *, task: Task, attempts: int, detail: str) -> None:
        """A task hit max errors and needs investigation."""
        ...
