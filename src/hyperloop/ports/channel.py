"""ChannelPort — interface for outbound notifications."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class ChannelPort(Protocol):
    """Send notifications about task/worker events."""

    def gate_blocked(self, *, task: Task, signal_name: str) -> None: ...

    def task_errored(self, *, task: Task, detail: str) -> None: ...

    def worker_crashed(self, *, task: Task, role: str, branch: str) -> None: ...
