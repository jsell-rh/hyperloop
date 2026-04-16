"""InMemoryRuntime — complete in-memory implementation of the Runtime port.

A first-class fake, tested via contract tests, reusable across all tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hyperloop.domain.model import WorkerHandle, WorkerResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from hyperloop.ports.runtime import WorkerPollStatus


@dataclass(frozen=True)
class SerialRunRecord:
    """Record of a serial agent invocation."""

    role: str
    prompt: str


class InMemoryRuntime:
    """In-memory implementation of the Runtime protocol."""

    def __init__(self) -> None:
        self._handles: dict[str, WorkerHandle] = {}
        self._poll_statuses: dict[str, WorkerPollStatus] = {}
        self._results: dict[str, WorkerResult] = {}
        self._reaped: set[str] = set()
        self._cancelled: set[str] = set()
        self._spawn_counter: int = 0
        self.serial_runs: list[SerialRunRecord] = []
        self._serial_callbacks: dict[str, Callable[[str], bool]] = {}
        self._serial_default_success: bool = True

    # -- Public accessors (for test assertions) -------------------------------

    @property
    def handles(self) -> dict[str, WorkerHandle]:
        """Expose spawned handles for test assertions."""
        return self._handles

    @property
    def cancelled(self) -> set[str]:
        """Expose cancelled task IDs for test assertions."""
        return self._cancelled

    # -- Configuration helpers (for tests) ----------------------------------

    def set_result(self, task_id: str, result: WorkerResult) -> None:
        """Pre-configure what reap() returns for a task."""
        self._results[task_id] = result

    def set_poll_status(self, task_id: str, status: WorkerPollStatus) -> None:
        """Pre-configure what poll() returns for a task."""
        self._poll_statuses[task_id] = status

    def set_serial_callback(self, role: str, callback: Callable[[str], bool]) -> None:
        """Register a callback for run_serial. Called with the prompt, returns success."""
        self._serial_callbacks[role] = callback

    def set_serial_default_success(self, success: bool) -> None:
        """Set the default return value for run_serial when no callback is registered."""
        self._serial_default_success = success

    # -- Runtime protocol ---------------------------------------------------

    def worker_epilogue(self) -> str:
        """Return empty string — in-memory runtime has no push requirement."""
        return ""

    def push_branch(self, branch: str) -> None:
        """Noop for in-memory runtime."""

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

    def poll(self, handle: WorkerHandle) -> WorkerPollStatus:
        """Check worker status. Returns 'running', 'done', or 'failed'."""
        task_id = handle.task_id
        if task_id in self._cancelled:
            return "failed"
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

    def run_serial(self, role: str, prompt: str) -> bool:
        """Record the invocation and optionally execute a callback."""
        self.serial_runs.append(SerialRunRecord(role=role, prompt=prompt))
        if role in self._serial_callbacks:
            return self._serial_callbacks[role](prompt)
        return self._serial_default_success
