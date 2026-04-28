"""InMemoryRuntime — complete in-memory implementation of the Runtime port.

A first-class fake, tested via contract tests, reusable across all tests.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hyperloop.domain.model import Verdict, WorkerHandle, WorkerPollStatus, WorkerResult

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class SerialRunRecord:
    """Record of a serial agent invocation."""

    role: str
    prompt: str


@dataclass(frozen=True)
class AuditorRunRecord:
    """Record of an auditor invocation."""

    spec_ref: str
    prompt: str


@dataclass(frozen=True)
class TrunkAgentRunRecord:
    """Record of a trunk agent invocation."""

    role: str
    prompt: str


@dataclass(frozen=True)
class TrunkPushRecord:
    """Record of a trunk push attempt, modelling the pull-then-push lifecycle."""

    role: str
    pull_attempted: bool
    pull_succeeded: bool
    push_attempted: bool
    push_succeeded: bool


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
        self.auditor_runs: list[AuditorRunRecord] = []
        self.trunk_agent_runs: list[TrunkAgentRunRecord] = []
        self.trunk_push_attempts: list[TrunkPushRecord] = []
        self._serial_callbacks: dict[str, Callable[[str], bool]] = {}
        self._auditor_callbacks: dict[str, Callable[[str], WorkerResult]] = {}
        self._trunk_agent_callbacks: dict[str, Callable[[str], WorkerResult]] = {}
        self._serial_default_success: bool = True
        self._auditor_default_result: WorkerResult = WorkerResult(
            verdict=Verdict.PASS, detail="fake"
        )
        self._trunk_agent_default_result: WorkerResult = WorkerResult(
            verdict=Verdict.PASS, detail="fake"
        )
        self._serial_lock = threading.Lock()
        self._trunk_push_fails: bool = False
        self._trunk_push_fails_until_pull: bool = False

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

    def set_auditor_callback(self, callback: Callable[[str], WorkerResult]) -> None:
        """Register a callback for run_auditor. Called with the prompt, returns WorkerResult."""
        self._auditor_callbacks["auditor"] = callback

    def set_auditor_default_result(self, result: WorkerResult) -> None:
        """Set the default WorkerResult for run_auditor when no callback is registered."""
        self._auditor_default_result = result

    def set_trunk_agent_callback(self, role: str, callback: Callable[[str], WorkerResult]) -> None:
        """Register a callback for run_trunk_agent. Called with the prompt, returns WorkerResult."""
        self._trunk_agent_callbacks[role] = callback

    def set_trunk_agent_default_result(self, result: WorkerResult) -> None:
        """Set the default WorkerResult for run_trunk_agent when no callback is registered."""
        self._trunk_agent_default_result = result

    def set_trunk_push_fails(self) -> None:
        """Simulate permanent remote divergence — push always fails after agent runs."""
        self._trunk_push_fails = True

    def set_trunk_push_fails_until_pull(self) -> None:
        """Push fails until pull --rebase is called (simulates remote-ahead).

        Models the exact production scenario: remote advances (e.g. PRs merged),
        push fails with non-fast-forward, pull --rebase fixes it, push succeeds.
        """
        self._trunk_push_fails_until_pull = True

    def advance_remote(self) -> None:
        """Simulate remote advancing (e.g. a PR merged on GitHub).

        After this call, the next trunk push will fail until pull --rebase
        reconciles local with remote. Equivalent to set_trunk_push_fails_until_pull
        but named to express intent in multi-agent test scenarios.
        """
        self._trunk_push_fails_until_pull = True

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
        self._poll_statuses.setdefault(task_id, WorkerPollStatus.RUNNING)
        # Remove stale reaped/cancelled state so this task is considered active
        self._reaped.discard(task_id)
        self._cancelled.discard(task_id)
        return handle

    def poll(self, handle: WorkerHandle) -> WorkerPollStatus:
        """Check worker status."""
        task_id = handle.task_id
        if task_id in self._cancelled:
            return WorkerPollStatus.FAILED
        return self._poll_statuses.get(task_id, WorkerPollStatus.RUNNING)

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

    def run_auditor(self, spec_ref: str, prompt: str) -> WorkerResult:
        """Record the invocation and optionally execute a callback.

        Returns WorkerResult with verdict and detail.
        """
        with self._serial_lock:
            self.auditor_runs.append(AuditorRunRecord(spec_ref=spec_ref, prompt=prompt))
            # Also record in serial_runs for backward compat with existing tests
            self.serial_runs.append(SerialRunRecord(role="auditor", prompt=prompt))
        if "auditor" in self._auditor_callbacks:
            return self._auditor_callbacks["auditor"](prompt)
        return self._auditor_default_result

    def run_trunk_agent(self, role: str, prompt: str) -> WorkerResult:
        """Record the invocation, model push lifecycle, and optionally execute a callback.

        Models the real AgentSdkRuntime._push_trunk() flow:
        1. Agent runs and commits to trunk.
        2. Pull --rebase is attempted to reconcile with remote.
        3. Push is attempted.

        Push failures are non-fatal — the agent result is always returned.
        The push lifecycle is recorded in trunk_push_attempts for test assertions.
        """
        with self._serial_lock:
            self.trunk_agent_runs.append(TrunkAgentRunRecord(role=role, prompt=prompt))
            # Also record in serial_runs for backward compat with existing tests
            self.serial_runs.append(SerialRunRecord(role=role, prompt=prompt))

        # Determine agent result first (push is post-agent)
        if role in self._trunk_agent_callbacks:
            agent_result = self._trunk_agent_callbacks[role](prompt)
        else:
            agent_result = self._trunk_agent_default_result

        # Model the push lifecycle (mirrors AgentSdkRuntime._push_trunk)
        push_record = self._simulate_trunk_push(role)
        self.trunk_push_attempts.append(push_record)

        return agent_result

    def _simulate_trunk_push(self, role: str) -> TrunkPushRecord:
        """Simulate the pull-then-push lifecycle of _push_trunk().

        Returns a TrunkPushRecord capturing what happened at each stage.
        """
        if self._trunk_push_fails:
            # Permanent failure: pull attempted, push attempted, both fail
            return TrunkPushRecord(
                role=role,
                pull_attempted=True,
                pull_succeeded=True,
                push_attempted=True,
                push_succeeded=False,
            )

        if self._trunk_push_fails_until_pull:
            # Remote was ahead — pull --rebase reconciles, then push succeeds
            self._trunk_push_fails_until_pull = False
            return TrunkPushRecord(
                role=role,
                pull_attempted=True,
                pull_succeeded=True,
                push_attempted=True,
                push_succeeded=True,
            )

        # Happy path: no divergence, pull and push both succeed
        return TrunkPushRecord(
            role=role,
            pull_attempted=True,
            pull_succeeded=True,
            push_attempted=True,
            push_succeeded=True,
        )
