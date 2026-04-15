"""InMemoryRuntime — complete in-memory implementation of the Runtime port.

A first-class fake, tested via contract tests, reusable across all tests.
"""

from __future__ import annotations

from hyperloop.domain.model import WorkerHandle, WorkerResult


class InMemoryRuntime:
    """In-memory implementation of the Runtime protocol."""

    def __init__(self) -> None:
        self._handles: dict[str, WorkerHandle] = {}
        self._poll_statuses: dict[str, str] = {}
        self._results: dict[str, WorkerResult] = {}
        self._reaped: set[str] = set()
        self._cancelled: set[str] = set()
        self._spawn_counter: int = 0

    # -- Configuration helpers (for tests) ----------------------------------

    def set_result(self, task_id: str, result: WorkerResult) -> None:
        """Pre-configure what reap() returns for a task."""
        self._results[task_id] = result

    def set_poll_status(self, task_id: str, status: str) -> None:
        """Pre-configure what poll() returns for a task."""
        self._poll_statuses[task_id] = status

    # -- Runtime protocol ---------------------------------------------------

    def spawn(self, task_id: str, role: str, prompt: str, branch: str) -> WorkerHandle:
        """Start a worker agent session. Returns an opaque handle."""
        self._spawn_counter += 1
        handle = WorkerHandle(
            task_id=task_id,
            role=role,
            agent_id=f"agent-{self._spawn_counter}",
            session_id=f"session-{self._spawn_counter}",
        )
        self._handles[task_id] = handle
        # Default to running unless pre-configured
        self._poll_statuses.setdefault(task_id, "running")
        # Remove stale reaped/cancelled state so this task is considered active
        self._reaped.discard(task_id)
        self._cancelled.discard(task_id)
        return handle

    def poll(self, handle: WorkerHandle) -> str:
        """Check worker status. Returns 'running', 'done', 'failed', or 'cancelled'."""
        task_id = handle.task_id
        if task_id in self._cancelled:
            return "cancelled"
        return self._poll_statuses.get(task_id, "running")

    def reap(self, handle: WorkerHandle) -> WorkerResult:
        """Collect the result from a finished worker and clean up."""
        task_id = handle.task_id
        self._reaped.add(task_id)
        return self._results[task_id]

    def cancel(self, handle: WorkerHandle) -> None:
        """Terminate a running worker session."""
        self._cancelled.add(handle.task_id)

    def find_orphan(self, task_id: str, branch: str) -> WorkerHandle | None:
        """Find a worker left running from a previous session (crash recovery).

        Returns the handle if the worker is still active (not reaped, not cancelled).
        Returns None otherwise.
        """
        if task_id not in self._handles:
            return None
        if task_id in self._reaped:
            return None
        if task_id in self._cancelled:
            return None
        return self._handles[task_id]
