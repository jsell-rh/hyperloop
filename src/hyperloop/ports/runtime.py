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

    def push_branch(self, branch: str) -> None:
        """Push a branch to the remote. Noop for local runtimes.

        Called before spawn() so remote runtimes (e.g. ambient) can
        access the branch.
        """
        ...

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

    def run_serial(self, role: str, prompt: str) -> bool:
        """Run an agent serially on trunk. Blocks until complete.

        Used for PM intake and process-improver. Returns True on success.
        """
        ...
