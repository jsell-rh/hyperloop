"""ActionPort — interface for executing pipeline actions.

Implementations: PRMergeAction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class ActionOutcome(Enum):
    """Result of an action execution."""

    SUCCESS = "success"
    RETRY = "retry"
    ERROR = "error"


@dataclass(frozen=True)
class ActionResult:
    """What an action adapter returns to the orchestrator."""

    outcome: ActionOutcome
    detail: str
    pr_url: str | None = None  # if set, orchestrator updates task.pr


class ActionPort(Protocol):
    """Execute pipeline actions (merge-pr, mark-pr-ready, post-pr-comment, etc.)."""

    def execute(self, task: Task, action_name: str, args: dict[str, object]) -> ActionResult:
        """Execute an action for a task. Args come from the process definition."""
        ...
