"""FakeSignalPort — in-memory implementation of the SignalPort.

A first-class fake, tested via contract tests, reusable across all tests.
"""

from __future__ import annotations

from hyperloop.domain.model import Signal, SignalStatus, Task


class FakeSignalPort:
    """In-memory SignalPort that returns configured signals."""

    def __init__(self) -> None:
        self._signals: dict[tuple[str, str], Signal] = {}
        self._default: Signal = Signal(status=SignalStatus.PENDING, message="")
        self.checked: list[tuple[str, str, dict[str, object]]] = []

    def set_signal(self, task_id: str, signal_name: str, signal: Signal) -> None:
        self._signals[(task_id, signal_name)] = signal

    def set_default(self, signal: Signal) -> None:
        self._default = signal

    def check(self, task: Task, signal_name: str, args: dict[str, object]) -> Signal:
        self.checked.append((task.id, signal_name, args))
        return self._signals.get((task.id, signal_name), self._default)
