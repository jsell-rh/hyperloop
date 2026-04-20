"""FakeNotification -- in-memory NotificationPort for testing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class FakeNotification:
    """Records all notification calls for test assertions."""

    def __init__(self) -> None:
        self.gate_blocked_calls: list[tuple[str, str]] = []  # (task_id, gate_name)
        self.task_errored_calls: list[tuple[str, int, str]] = []  # (task_id, attempts, detail)

    def gate_blocked(self, *, task: Task, gate_name: str) -> None:
        """Record a gate_blocked notification."""
        self.gate_blocked_calls.append((task.id, gate_name))

    def task_errored(self, *, task: Task, attempts: int, detail: str) -> None:
        """Record a task_errored notification."""
        self.task_errored_calls.append((task.id, attempts, detail))
