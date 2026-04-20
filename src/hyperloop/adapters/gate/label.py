"""LabelGate -- checks for 'lgtm' label on a task's PR."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperloop.domain.model import Task
    from hyperloop.ports.pr import PRPort


class LabelGate:
    """GatePort adapter that checks for a label on the task's PR."""

    def __init__(self, pr: PRPort) -> None:
        self._pr = pr

    def check(self, task: Task, gate_name: str) -> bool:
        """Return True if the gate is cleared for this task.

        Handles PR state: if MERGED, returns True. If CLOSED, returns False
        (orchestrator will handle recreation). If no PR, returns False.
        """
        if task.pr is None:
            return False

        # Check PR state first
        pr_state = self._pr.get_pr_state(task.pr)
        if pr_state is not None:
            if pr_state.state == "MERGED":
                return True  # Gate is moot -- PR already merged
            if pr_state.state == "CLOSED":
                return False  # PR needs recreation

        return self._pr.check_gate(task.pr, gate_name)
