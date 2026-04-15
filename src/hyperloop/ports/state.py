"""StateStore port — interface for persisting orchestrator state.

Implementations: GitStateStore (git commits), AmbientStateStore (platform API).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from hyperloop.domain.model import Phase, Task, TaskStatus, World


class StateStore(Protocol):
    """Read and write orchestrator state (tasks, findings, epochs)."""

    def get_world(self) -> World:
        """Return a complete snapshot of all tasks, workers, and the current epoch."""
        ...

    def get_task(self, task_id: str) -> Task:
        """Return a single task by ID."""
        ...

    def transition_task(
        self,
        task_id: str,
        status: TaskStatus,
        phase: Phase | None,
        round: int | None = None,
    ) -> None:
        """Update a task's status, phase, and optionally round."""
        ...

    def store_findings(self, task_id: str, detail: str) -> None:
        """Append findings detail text to the task file's Findings section on trunk."""
        ...

    def get_findings(self, task_id: str) -> str:
        """Return stored findings for a task. Empty string if none."""
        ...

    def clear_findings(self, task_id: str) -> None:
        """Clear the findings section of a task file (on completion)."""
        ...

    def get_epoch(self, key: str) -> str:
        """Return the content fingerprint for skip logic."""
        ...

    def set_epoch(self, key: str, value: str) -> None:
        """Record a last-run marker."""
        ...

    def list_files(self, pattern: str) -> list[str]:
        """List file paths matching a glob pattern relative to the repo root."""
        ...

    def read_file(self, path: str) -> str | None:
        """Read a file from trunk. Returns None if the file does not exist."""
        ...

    def set_task_branch(self, task_id: str, branch: str) -> None:
        """Set the branch name on a task (called once, before first spawn)."""
        ...

    def set_task_pr(self, task_id: str, pr_url: str) -> None:
        """Set the PR URL on a task."""
        ...

    def commit(self, message: str) -> None:
        """Persist all pending state changes."""
        ...
