"""Runtime port — interface for managing worker agent sessions.

Implementations: AgentSdkRuntime (worktrees + Claude Agent SDK).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from hyperloop.domain.model import WorkerHandle, WorkerPollStatus, WorkerResult


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

    def worker_epilogue(self) -> str:
        """Runtime-specific instructions appended to every worker prompt.

        Returns an empty string for local runtimes. Remote runtimes (e.g. ambient)
        return instructions like 'Push your branch when done.'
        """
        ...

    def run_auditor(self, spec_ref: str, prompt: str) -> WorkerResult:
        """Run an isolated read-only auditor. Returns verdict with detail.

        SDK: creates detached worktree, runs agent, reads verdict, cleans up.
        Ambient: creates session, blocks until complete, reads verdict.
        Safe to call concurrently from multiple threads.
        """
        ...

    def run_trunk_agent(self, role: str, prompt: str) -> WorkerResult:
        """Run a mutating agent on trunk (PM, process-improver). Blocks until complete.

        Agent can commit to trunk. Runtime pushes trunk after success.
        Returns WorkerResult with verdict and detail.
        Must NOT be called concurrently.
        """
        ...
