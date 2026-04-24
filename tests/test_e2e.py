"""End-to-end tests -- real GitStateStore + InMemoryRuntime.

Validates the full orchestrator loop against a real git repo without
requiring the Agent SDK or API credentials.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from hyperloop.adapters.git.state import GitStateStore
from hyperloop.domain.model import (
    PhaseStep,
    Process,
    Task,
    TaskStatus,
    Verdict,
    WorkerPollStatus,
    WorkerResult,
)
from hyperloop.loop import Orchestrator
from tests.fakes.probe import RecordingProbe
from tests.fakes.runtime import InMemoryRuntime

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS_RESULT = WorkerResult(verdict=Verdict.PASS, detail="All tests pass")
FAIL_RESULT = WorkerResult(verdict=Verdict.FAIL, detail="Tests failed")

DEFAULT_PROCESS = Process(
    name="default",
    phases={
        "implement": PhaseStep(run="agent implementer", on_pass="verify", on_fail="implement"),
        "verify": PhaseStep(run="agent verifier", on_pass="done", on_fail="implement"),
    },
)

SEED_TASK = Task(
    id="task-001",
    title="Implement feature",
    spec_ref="specs/example.md",
    status=TaskStatus.NOT_STARTED,
    phase=None,
    deps=(),
    round=0,
    branch=None,
    pr=None,
)


def _init_repo(path: Path) -> None:
    """Create a git repo with an initial empty commit."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "--no-verify", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )


def _commit_all(repo: Path, message: str) -> None:
    """Stage all changes and commit."""
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--no-verify", "-m", message],
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSingleTaskCompletesE2E:
    """Full loop: not-started -> implementer -> verifier -> completed,
    with a real GitStateStore and fake runtime."""

    def test_single_task_completes(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)

        # Write a spec file so the task's spec_ref is resolvable
        specs_dir = repo / "specs"
        specs_dir.mkdir()
        (specs_dir / "example.md").write_text("# Example spec\nBuild a widget.")
        _commit_all(repo, "add spec")

        # Construct real state store and seed task via store API
        state = GitStateStore(repo_path=repo)
        state.add_task(SEED_TASK)
        state.persist("seed task-001")
        runtime = InMemoryRuntime()
        probe = RecordingProbe()

        orch = Orchestrator(
            state=state,
            runtime=runtime,
            process=DEFAULT_PROCESS,
            poll_interval=0,
            probe=probe,
        )

        # Cycle 1: orchestrator spawns implementer
        orch.run_cycle(cycle_num=1)
        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase is not None
        assert str(task.phase) == "implement"

        # Simulate implementer completing with pass
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: reap implementer, advance to verify
        orch.run_cycle(cycle_num=2)
        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase is not None
        assert str(task.phase) == "verify"

        # Simulate verifier completing with pass
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 3: reap verifier, on_pass="done" -> COMPLETED
        orch.run_cycle(cycle_num=3)
        task = state.get_task("task-001")
        assert task.status == TaskStatus.COMPLETED

        # Verify probe events were recorded
        spawned = probe.of_method("worker_spawned")
        assert len(spawned) >= 2
        completed = probe.of_method("task_completed")
        assert len(completed) == 1
        assert completed[0]["task_id"] == "task-001"


class TestFailedVerificationRetriesE2E:
    """Verifier fails -> round increments, task loops back to implementer."""

    def test_failed_verification_increments_round(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)

        specs_dir = repo / "specs"
        specs_dir.mkdir()
        (specs_dir / "example.md").write_text("# Example spec\nBuild a widget.")
        _commit_all(repo, "add spec")

        state = GitStateStore(repo_path=repo)
        state.add_task(SEED_TASK)
        state.persist("seed task-001")
        runtime = InMemoryRuntime()
        probe = RecordingProbe()

        orch = Orchestrator(
            state=state,
            runtime=runtime,
            process=DEFAULT_PROCESS,
            poll_interval=0,
            probe=probe,
        )

        # Cycle 1: spawn implementer
        orch.run_cycle(cycle_num=1)
        task = state.get_task("task-001")
        assert str(task.phase) == "implement"

        # Implementer passes
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: reap implementer, advance to verify
        orch.run_cycle(cycle_num=2)
        task = state.get_task("task-001")
        assert str(task.phase) == "verify"

        # Verifier fails
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", FAIL_RESULT)

        # Cycle 3: reap verifier failure, loop back, round increments
        orch.run_cycle(cycle_num=3)
        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.round == 1
        assert str(task.phase) == "implement"

        # Verify retry probe event
        retried = probe.of_method("task_retried")
        assert len(retried) == 1
        assert retried[0]["task_id"] == "task-001"
        assert retried[0]["round"] == 1
