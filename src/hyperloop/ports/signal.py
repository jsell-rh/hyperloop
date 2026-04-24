"""SignalPort — interface for checking external signals (gate replacement)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from hyperloop.domain.model import Signal, Task


class SignalPort(Protocol):
    """Check the status of a named signal for a task."""

    def check(self, task: Task, signal_name: str, args: dict[str, object]) -> Signal: ...
