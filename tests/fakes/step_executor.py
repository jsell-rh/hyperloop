"""FakeStepExecutor — in-memory implementation of the StepExecutor port.

A first-class fake, tested via contract tests, reusable across all tests.
"""

from __future__ import annotations

from hyperloop.domain.model import StepOutcome, StepResult, Task


class FakeStepExecutor:
    """In-memory StepExecutor that returns configured results."""

    def __init__(self) -> None:
        self._results: dict[tuple[str, str], StepResult] = {}
        self._default: StepResult = StepResult(outcome=StepOutcome.ADVANCE, detail="OK")
        self.executed: list[tuple[str, str, dict[str, object]]] = []

    def set_result(self, task_id: str, step_name: str, result: StepResult) -> None:
        self._results[(task_id, step_name)] = result

    def set_default(self, result: StepResult) -> None:
        self._default = result

    def execute(self, task: Task, step_name: str, args: dict[str, object]) -> StepResult:
        self.executed.append((task.id, step_name, args))
        return self._results.get((task.id, step_name), self._default)
