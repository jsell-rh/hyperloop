"""Integration tests for LocalRuntime.

Exercises the adapter against real git repos and subprocesses.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import TYPE_CHECKING

import pytest

from hyperloop.adapters.runtime import LocalRuntime
from hyperloop.domain.model import Verdict

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_git_env() -> dict[str, str]:
    """Strip GIT_* env vars so tests work inside pre-commit hooks."""
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("GIT_"):
            del env[key]
    return env


def _init_repo(path: Path) -> None:
    """Create a git repo with an initial empty commit."""
    env = _clean_git_env()
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True, env=env)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "--no-verify", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
        env=env,
    )


# Shell commands for testing. These are passed directly as the `command` arg
# to LocalRuntime (which runs them with shell=True), so no bash -c wrapper needed.
PASS_COMMAND = (
    'printf \'%s\' \'{"verdict":"pass","findings":0,"detail":"ok"}\' > .worker-result.json'
)

FAIL_COMMAND = (
    'printf \'%s\' \'{"verdict":"fail","findings":2,"detail":"tests broke"}\''
    " > .worker-result.json && exit 1"
)

SLOW_COMMAND = "sleep 60"


# ---------------------------------------------------------------------------
# Tests — Spawn
# ---------------------------------------------------------------------------


class TestSpawn:
    def test_creates_worktree_and_returns_handle(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=PASS_COMMAND)

        handle = rt.spawn("task-001", "implementer", "Do the work.", "hyperloop/task-001")

        assert handle.task_id == "task-001"
        assert handle.role == "implementer"
        # agent_id should be the PID (a string of digits)
        assert handle.agent_id.isdigit()

    def test_worktree_directory_exists_after_spawn(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=PASS_COMMAND)

        rt.spawn("task-002", "implementer", "Do the work.", "hyperloop/task-002")

        worktree_path = tmp_path / "worktrees" / "workers" / "task-002"
        assert worktree_path.is_dir()

    def test_prompt_file_written_to_worktree(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=PASS_COMMAND)

        rt.spawn("task-003", "verifier", "Check the code.", "hyperloop/task-003")

        prompt_path = tmp_path / "worktrees" / "workers" / "task-003" / "prompt.md"
        assert prompt_path.exists()
        assert prompt_path.read_text() == "Check the code."

    def test_worktree_is_on_correct_branch(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=PASS_COMMAND)

        rt.spawn("task-004", "implementer", "Do stuff.", "hyperloop/task-004")

        worktree_path = tmp_path / "worktrees" / "workers" / "task-004"
        result = subprocess.run(
            ["git", "-C", str(worktree_path), "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
            env=_clean_git_env(),
        )
        assert result.stdout.strip() == "hyperloop/task-004"


# ---------------------------------------------------------------------------
# Tests — Poll
# ---------------------------------------------------------------------------


class TestPoll:
    def test_returns_running_while_process_alive(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=SLOW_COMMAND)

        handle = rt.spawn("task-010", "implementer", "prompt", "hyperloop/task-010")

        assert rt.poll(handle) == "running"
        # Clean up
        rt.cancel(handle)

    def test_returns_done_when_exit_zero(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=PASS_COMMAND)

        handle = rt.spawn("task-011", "implementer", "prompt", "hyperloop/task-011")

        # Wait for fast command to finish
        deadline = time.monotonic() + 5
        while rt.poll(handle) == "running":
            if time.monotonic() > deadline:
                pytest.fail("Process did not finish within 5 seconds")
            time.sleep(0.05)

        assert rt.poll(handle) == "done"

    def test_returns_failed_when_exit_nonzero(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=FAIL_COMMAND)

        handle = rt.spawn("task-012", "implementer", "prompt", "hyperloop/task-012")

        deadline = time.monotonic() + 5
        while rt.poll(handle) == "running":
            if time.monotonic() > deadline:
                pytest.fail("Process did not finish within 5 seconds")
            time.sleep(0.05)

        assert rt.poll(handle) == "failed"


# ---------------------------------------------------------------------------
# Tests — Reap
# ---------------------------------------------------------------------------


class TestReap:
    def test_reads_worker_result_from_worktree(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=PASS_COMMAND)

        handle = rt.spawn("task-020", "implementer", "prompt", "hyperloop/task-020")

        # Wait for completion
        deadline = time.monotonic() + 5
        while rt.poll(handle) == "running":
            if time.monotonic() > deadline:
                pytest.fail("Process did not finish within 5 seconds")
            time.sleep(0.05)

        result = rt.reap(handle)

        assert result.verdict == Verdict.PASS
        assert result.findings == 0
        assert result.detail == "ok"

    def test_reads_failed_worker_result(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=FAIL_COMMAND)

        handle = rt.spawn("task-021", "implementer", "prompt", "hyperloop/task-021")

        deadline = time.monotonic() + 5
        while rt.poll(handle) == "running":
            if time.monotonic() > deadline:
                pytest.fail("Process did not finish within 5 seconds")
            time.sleep(0.05)

        result = rt.reap(handle)

        assert result.verdict == Verdict.FAIL
        assert result.findings == 2
        assert result.detail == "tests broke"

    def test_cleans_up_worktree_after_reap(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=PASS_COMMAND)

        handle = rt.spawn("task-022", "implementer", "prompt", "hyperloop/task-022")

        deadline = time.monotonic() + 5
        while rt.poll(handle) == "running":
            if time.monotonic() > deadline:
                pytest.fail("Process did not finish within 5 seconds")
            time.sleep(0.05)

        rt.reap(handle)

        worktree_path = tmp_path / "worktrees" / "workers" / "task-022"
        assert not worktree_path.exists()

    def test_preserves_branch_after_reap(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=PASS_COMMAND)

        handle = rt.spawn("task-023", "implementer", "prompt", "hyperloop/task-023")

        deadline = time.monotonic() + 5
        while rt.poll(handle) == "running":
            if time.monotonic() > deadline:
                pytest.fail("Process did not finish within 5 seconds")
            time.sleep(0.05)

        rt.reap(handle)

        # Branch should be preserved for later pipeline steps (e.g. merge-pr)
        result = subprocess.run(
            ["git", "-C", str(tmp_path), "branch", "--list", "hyperloop/task-023"],
            check=True,
            capture_output=True,
            text=True,
            env=_clean_git_env(),
        )
        assert "hyperloop/task-023" in result.stdout.strip()

    def test_returns_error_result_when_no_result_file(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        # Command that exits 0 but doesn't write a result file
        rt = LocalRuntime(repo_path=str(tmp_path), command="echo done")

        handle = rt.spawn("task-024", "implementer", "prompt", "hyperloop/task-024")

        deadline = time.monotonic() + 5
        while rt.poll(handle) == "running":
            if time.monotonic() > deadline:
                pytest.fail("Process did not finish within 5 seconds")
            time.sleep(0.05)

        result = rt.reap(handle)

        assert result.verdict == Verdict.ERROR
        assert "result file" in result.detail.lower() or "not found" in result.detail.lower()


# ---------------------------------------------------------------------------
# Tests — Cancel
# ---------------------------------------------------------------------------


class TestCancel:
    def test_kills_running_process(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=SLOW_COMMAND)

        handle = rt.spawn("task-030", "implementer", "prompt", "hyperloop/task-030")
        assert rt.poll(handle) == "running"

        rt.cancel(handle)

        # Process should no longer be running
        status = rt.poll(handle)
        assert status != "running"

    def test_cleans_up_worktree(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=SLOW_COMMAND)

        handle = rt.spawn("task-031", "implementer", "prompt", "hyperloop/task-031")
        rt.cancel(handle)

        worktree_path = tmp_path / "worktrees" / "workers" / "task-031"
        assert not worktree_path.exists()

    def test_cleans_up_branch(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=SLOW_COMMAND)

        handle = rt.spawn("task-032", "implementer", "prompt", "hyperloop/task-032")
        rt.cancel(handle)

        result = subprocess.run(
            ["git", "-C", str(tmp_path), "branch", "--list", "hyperloop/task-032"],
            check=True,
            capture_output=True,
            text=True,
            env=_clean_git_env(),
        )
        assert result.stdout.strip() == ""

    def test_cancel_already_dead_process_does_not_raise(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=PASS_COMMAND)

        handle = rt.spawn("task-033", "implementer", "prompt", "hyperloop/task-033")

        # Wait for completion
        deadline = time.monotonic() + 5
        while rt.poll(handle) == "running":
            if time.monotonic() > deadline:
                pytest.fail("Process did not finish within 5 seconds")
            time.sleep(0.05)

        # Should not raise even though process is already dead
        rt.cancel(handle)


# ---------------------------------------------------------------------------
# Tests — Find Orphan
# ---------------------------------------------------------------------------


class TestFindOrphan:
    def test_returns_handle_when_worktree_exists(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=SLOW_COMMAND)

        handle = rt.spawn("task-040", "implementer", "prompt", "hyperloop/task-040")

        # Create a NEW runtime instance (simulating crash recovery)
        rt2 = LocalRuntime(repo_path=str(tmp_path), command=SLOW_COMMAND)

        orphan = rt2.find_orphan("task-040", "hyperloop/task-040")

        assert orphan is not None
        assert orphan.task_id == "task-040"

        # Clean up
        rt.cancel(handle)

    def test_returns_none_when_no_worktree(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=PASS_COMMAND)

        orphan = rt.find_orphan("task-041", "hyperloop/task-041")

        assert orphan is None

    def test_returns_none_after_reap_cleans_up(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rt = LocalRuntime(repo_path=str(tmp_path), command=PASS_COMMAND)

        handle = rt.spawn("task-042", "implementer", "prompt", "hyperloop/task-042")

        deadline = time.monotonic() + 5
        while rt.poll(handle) == "running":
            if time.monotonic() > deadline:
                pytest.fail("Process did not finish within 5 seconds")
            time.sleep(0.05)

        rt.reap(handle)

        orphan = rt.find_orphan("task-042", "hyperloop/task-042")
        assert orphan is None
