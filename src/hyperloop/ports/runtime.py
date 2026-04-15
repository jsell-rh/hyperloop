"""Runtime port — interface for managing worker agent sessions.

Implementations: LocalRuntime (worktrees + CLI), AmbientRuntime (platform API).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from hyperloop.domain.model import WorkerHandle, WorkerResult

WorkerPollStatus = Literal["running", "done", "failed"]


class Runtime(Protocol):
    """Spawn, poll, and collect results from worker agents."""

    def spawn(self, task_id: str, role: str, prompt: str, branch: str) -> WorkerHandle:
        """Start a worker agent session on the given branch."""
        ...

    def poll(self, handle: WorkerHandle) -> WorkerPollStatus:
        """Check worker status. Returns 'running', 'done', or 'failed'."""
        ...

    def reap(self, handle: WorkerHandle) -> WorkerResult:
        """Collect the result from a finished worker and clean up."""
        ...

    def cancel(self, handle: WorkerHandle) -> None:
        """Terminate a running worker session."""
        ...

    def find_orphan(self, task_id: str, branch: str) -> WorkerHandle | None:
        """Find a worker left running from a previous orchestrator session (crash recovery)."""
        ...
