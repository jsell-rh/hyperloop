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

    def add_task(self, task: Task) -> None:
        """Add a new task to the store."""
        ...

    def store_review(
        self,
        task_id: str,
        round: int,
        role: str,
        verdict: str,
        detail: str,
    ) -> None:
        """Write a review file for a task round."""
        ...

    def get_findings(self, task_id: str) -> str:
        """Return findings from the latest review for a task. Empty string if none."""
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

    def set_spec_ref(self, task_id: str, spec_ref: str) -> None:
        """Pin the spec_ref on a task (e.g. append @sha after intake)."""
        ...

    def persist(self, message: str) -> None:
        """Persist all pending state changes."""
        ...

    def reset_task(self, task_id: str) -> None:
        """Reset a task to not-started with cleared branch, PR, and round.

        Used when a branch is poisoned (e.g. unrebaseable due to state file
        history) and the task needs a fresh start.
        """
        ...

    def delete_task(self, task_id: str) -> None:
        """Remove a task from the store (used by GC pruning)."""
        ...

    def sync(self) -> None:
        """Sync state with remote (pull then push). Called once per cycle boundary."""
        ...
