"""CheckPort — mechanical pass/fail evaluations for pipeline check steps."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class CheckPort(Protocol):
    """Interface for mechanical checks that return pass/fail."""

    def evaluate(self, task: Task, check_name: str, args: dict[str, object]) -> bool:
        """Evaluate a named check for a task. Args come from the process definition."""
        ...
