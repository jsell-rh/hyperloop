"""FakeGate -- in-memory implementation of GatePort for testing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class FakeGate:
    """In-memory GatePort implementation.

    Pre-configure which task IDs have cleared gates via ``set_cleared``.
    All ``check`` calls are recorded for assertion.
    """

    def __init__(self) -> None:
        self._cleared: set[str] = set()  # task_ids with cleared gates
        self.checked: list[tuple[str, str]] = []  # (task_id, gate_name)

    def set_cleared(self, task_id: str) -> None:
        """Pre-configure a task's gate as cleared."""
        self._cleared.add(task_id)

    def check(self, task: Task, gate_name: str) -> bool:
        """Return True if the task's gate has been pre-cleared."""
        self.checked.append((task.id, gate_name))
        return task.id in self._cleared
