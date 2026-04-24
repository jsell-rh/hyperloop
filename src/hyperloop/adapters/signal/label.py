"""LabelSignal -- checks for a configurable label on a task's PR.

Returns Signal with APPROVED/PENDING/REJECTED status.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hyperloop.domain.model import Signal, SignalStatus

if TYPE_CHECKING:
    from hyperloop.domain.model import Task
    from hyperloop.ports.pr import PRPort


class LabelSignal:
    """SignalPort adapter that checks for a label on the task's PR."""

    def __init__(self, pr: PRPort, label: str = "lgtm") -> None:
        self._pr = pr
        self._label = label

    def check(self, task: Task, signal_name: str, args: dict[str, object]) -> Signal:
        """Check if the gate label is present on the task's PR.

        Returns:
            APPROVED -- label present or PR already merged
            REJECTED -- PR is closed
            PENDING -- label not yet present, or no PR
        """
        if task.pr is None:
            return Signal(status=SignalStatus.PENDING, message="No PR")

        pr_state = self._pr.get_pr_state(task.pr)
        if pr_state is not None:
            if pr_state.state == "MERGED":
                return Signal(status=SignalStatus.APPROVED, message="PR already merged")
            if pr_state.state == "CLOSED":
                return Signal(status=SignalStatus.REJECTED, message="PR is closed")

        if self._pr.check_gate(task.pr, signal_name):
            return Signal(status=SignalStatus.APPROVED, message="Label present")

        return Signal(status=SignalStatus.PENDING, message="Waiting for label")
