"""FakeAction -- in-memory implementation of ActionPort for testing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hyperloop.ports.action import ActionOutcome, ActionResult

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class FakeAction:
    """In-memory ActionPort implementation.

    Pre-configure results per task via ``set_result``, or set a default
    via ``set_default``. All ``execute`` calls are recorded for assertion.
    """

    def __init__(self) -> None:
        self._results: dict[str, ActionResult] = {}  # task_id -> result
        self._default = ActionResult(outcome=ActionOutcome.SUCCESS, detail="OK")
        self.executed: list[tuple[str, str]] = []  # (task_id, action_name)

    def set_result(self, task_id: str, result: ActionResult) -> None:
        """Pre-configure the result for a specific task."""
        self._results[task_id] = result

    def set_default(self, result: ActionResult) -> None:
        """Set the default result for tasks without specific config."""
        self._default = result

    def execute(self, task: Task, action_name: str) -> ActionResult:
        """Execute an action and record the call."""
        self.executed.append((task.id, action_name))
        return self._results.get(task.id, self._default)
