"""GatePort — interface for evaluating external gate signals.

Implementations: LabelGate, PRApprovalGate, CIStatusGate, AllGate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class GatePort(Protocol):
    """Gates block until an external signal is received."""

    def check(self, task: Task, gate_name: str) -> bool:
        """Return True if the gate is cleared for this task."""
        ...
