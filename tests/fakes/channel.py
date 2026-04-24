"""FakeChannelPort — in-memory implementation of the ChannelPort.

A first-class fake, tested via contract tests, reusable across all tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class FakeChannelPort:
    """In-memory ChannelPort that records all notification calls."""

    def __init__(self) -> None:
        self.gate_blocked_calls: list[tuple[str, str]] = []
        self.task_errored_calls: list[tuple[str, str]] = []
        self.worker_crashed_calls: list[tuple[str, str, str]] = []

    def gate_blocked(self, *, task: Task, signal_name: str) -> None:
        self.gate_blocked_calls.append((task.id, signal_name))

    def task_errored(self, *, task: Task, detail: str) -> None:
        self.task_errored_calls.append((task.id, detail))

    def worker_crashed(self, *, task: Task, role: str, branch: str) -> None:
        self.worker_crashed_calls.append((task.id, role, branch))
