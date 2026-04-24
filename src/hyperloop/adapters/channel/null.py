"""NullChannel -- no-op channel adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class NullChannel:
    """ChannelPort adapter that does nothing."""

    def gate_blocked(self, *, task: Task, signal_name: str) -> None:
        pass

    def task_errored(self, *, task: Task, detail: str) -> None:
        pass

    def worker_crashed(self, *, task: Task, role: str, branch: str) -> None:
        pass
