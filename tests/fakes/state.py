"""InMemoryStateStore — complete in-memory implementation of the StateStore port.

A first-class fake, tested via contract tests, reusable across all tests.
"""

from __future__ import annotations

from hyperloop.domain.model import (
    Phase,
    Task,
    TaskStatus,
    World,
)


class InMemoryStateStore:
    """In-memory implementation of the StateStore protocol."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._findings: dict[str, str] = {}
        self._epochs: dict[str, str] = {}
        self._files: dict[str, str] = {}
        self.committed_messages: list[str] = []

    # -- Setup helpers (for tests) ------------------------------------------

    def add_task(self, task: Task) -> None:
        """Seed a task into the store (test helper, not part of the port)."""
        self._tasks[task.id] = task
        self._findings.setdefault(task.id, "")

    def set_file(self, path: str, content: str) -> None:
        """Seed a file into the store (test helper, not part of the port)."""
        self._files[path] = content

    def get_findings(self, task_id: str) -> str:
        """Return stored findings for a task (test helper)."""
        return self._findings.get(task_id, "")

    def set_task_pr(self, task_id: str, pr_url: str) -> None:
        """Set the PR URL on a task (test helper, not part of the port)."""
        old = self._tasks[task_id]
        self._tasks[task_id] = Task(
            id=old.id,
            title=old.title,
            spec_ref=old.spec_ref,
            status=old.status,
            phase=old.phase,
            deps=old.deps,
            round=old.round,
            branch=old.branch,
            pr=pr_url,
        )

    # -- StateStore protocol ------------------------------------------------

    def get_world(self) -> World:
        """Return a complete snapshot of all tasks, workers, and the current epoch."""
        return World(
            tasks=dict(self._tasks),
            workers={},
            epoch=self._epochs.get("intake", ""),
        )

    def get_task(self, task_id: str) -> Task:
        """Return a single task by ID. Raises KeyError if not found."""
        return self._tasks[task_id]

    def transition_task(
        self,
        task_id: str,
        status: TaskStatus,
        phase: Phase | None,
        round: int | None = None,
    ) -> None:
        """Update a task's status, phase, and optionally round."""
        old = self._tasks[task_id]
        self._tasks[task_id] = Task(
            id=old.id,
            title=old.title,
            spec_ref=old.spec_ref,
            status=status,
            phase=phase,
            deps=old.deps,
            round=round if round is not None else old.round,
            branch=old.branch,
            pr=old.pr,
        )

    def store_findings(self, task_id: str, detail: str) -> None:
        """Append findings to the task's findings string."""
        self._findings[task_id] = self._findings.get(task_id, "") + detail

    def clear_findings(self, task_id: str) -> None:
        """Clear findings for a task."""
        self._findings[task_id] = ""

    def get_epoch(self, key: str) -> str:
        """Return the content fingerprint for skip logic. Empty string if unset."""
        return self._epochs.get(key, "")

    def set_epoch(self, key: str, value: str) -> None:
        """Record a last-run marker."""
        self._epochs[key] = value

    def list_files(self, pattern: str) -> list[str]:
        """List file paths matching a glob pattern against in-memory files.

        Uses PurePosixPath.match to respect directory boundaries (``*`` does
        not cross ``/``), consistent with pathlib.Path.glob behaviour.
        """
        from pathlib import PurePosixPath

        return sorted(p for p in self._files if PurePosixPath(p).match(pattern))

    def read_file(self, path: str) -> str | None:
        """Read a file from the in-memory filesystem. Returns None if not found."""
        return self._files.get(path)

    def commit(self, message: str) -> None:
        """Record the commit message (no-op for in-memory, but stores for test assertions)."""
        self.committed_messages.append(message)
