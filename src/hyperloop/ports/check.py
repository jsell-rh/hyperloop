"""CheckPort — evaluation for pipeline check steps."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class CheckResult(Enum):
    """Three-valued outcome of a check evaluation.

    PASS — advance to next pipeline step.
    FAIL — restart enclosing loop (agent needs to do more work).
    WAIT — stay at this step, re-evaluate next cycle (external event pending).
    """

    PASS = "pass"
    FAIL = "fail"
    WAIT = "wait"


class CheckPort(Protocol):
    """Interface for check evaluations — mechanical or agent-backed."""

    def evaluate(self, task: Task, check_name: str, args: dict[str, object]) -> CheckResult:
        """Evaluate a named check for a task. Args come from the process definition."""
        ...
