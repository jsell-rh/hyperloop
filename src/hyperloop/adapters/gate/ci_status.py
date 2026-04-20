"""CIStatusGate -- checks for CI status on a task's PR.

Stub implementation -- not yet wired.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class CIStatusGate:
    """GatePort adapter that checks CI status checks."""

    def check(self, task: Task, gate_name: str) -> bool:
        """Return True if the gate is cleared for this task."""
        raise NotImplementedError
