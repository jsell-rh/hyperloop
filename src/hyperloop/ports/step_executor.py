"""StepExecutor port — interface for executing phase steps."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from hyperloop.domain.model import StepResult, Task


class StepExecutor(Protocol):
    """Execute a named step against a task and return the outcome."""

    def execute(self, task: Task, step_name: str, args: dict[str, object]) -> StepResult: ...
