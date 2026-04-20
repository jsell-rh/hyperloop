"""NullNotification -- no-op notification adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class NullNotification:
    """NotificationPort adapter that does nothing."""

    def gate_blocked(self, *, task: Task, gate_name: str) -> None:
        pass

    def task_errored(self, *, task: Task, attempts: int, detail: str) -> None:
        pass
