"""AllGate -- composite gate that requires all sub-gates to pass.

Stub implementation -- not yet wired.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperloop.domain.model import Task
    from hyperloop.ports.gate import GatePort


class AllGate:
    """GatePort adapter that requires all sub-gates to pass."""

    def __init__(self, gates: tuple[GatePort, ...]) -> None:
        self._gates = gates

    def check(self, task: Task, gate_name: str) -> bool:
        """Return True if all sub-gates are cleared for this task."""
        raise NotImplementedError
