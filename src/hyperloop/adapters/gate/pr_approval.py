"""PRApprovalGate -- checks for PR approval status.

Stub implementation -- not yet wired.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class PRApprovalGate:
    """GatePort adapter that checks for PR approval."""

    def check(self, task: Task, gate_name: str) -> bool:
        """Return True if the gate is cleared for this task."""
        raise NotImplementedError
