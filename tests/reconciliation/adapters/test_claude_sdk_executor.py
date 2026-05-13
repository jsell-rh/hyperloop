from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hyperloop.reconciliation.adapters.claude_sdk_executor import ClaudeSDKExecutor
from hyperloop.reconciliation.models.executor_timeout_error import ExecutorTimeoutError
from hyperloop.reconciliation.models.integration_summary import IntegrationSummary
from hyperloop.reconciliation.models.proposed_task import ProposedTask

from tests.reconciliation.fakes.fake_sdk_runner import FakeSDKRunner


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


def _create_branch(repo: Path, branch: str) -> None:
    _git(repo, "branch", branch, "main")


def _branch_exists(repo: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", branch],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _worktree_paths(repo: Path) -> list[Path]:
    result = _git(repo, "worktree", "list", "--porcelain")
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line.split(" ", 1)[1]))
    return paths


def _make_executor(
    repo: Path,
    runner: FakeSDKRunner,
    *,
    timeout_seconds: int = 300,
    max_retries: int = 3,
) -> ClaudeSDKExecutor:
    return ClaudeSDKExecutor(
        repo_path=repo,
        sdk_runner=runner,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )


TASK_BRANCH = "hyperloop/spec/abc123/task/5"
VERIFIER_BRANCH = "hyperloop/spec/abc123/verifier"


class TestAsyncWorktreeCreation:
    def test_start_task_agent_creates_worktree_from_branch(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Do work")

        worktrees = _worktree_paths(repo)
        assert len(worktrees) == 2  # main repo + new worktree

    def test_start_task_agent_runs_agent_in_worktree_directory(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Do work")

        assert len(runner.async_calls) == 1
        cwd = runner.async_calls[0]["cwd"]
        assert isinstance(cwd, Path)
        assert cwd.exists()
        assert cwd != repo

    def test_start_verification_agent_creates_worktree(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, VERIFIER_BRANCH)

        executor.start_verification_agent(branch=VERIFIER_BRANCH, prompt="Verify")

        worktrees = _worktree_paths(repo)
        assert len(worktrees) == 2

    def test_start_task_agent_passes_prompt_to_sdk(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Do specific work")

        assert runner.async_calls[0]["prompt"] == "Do specific work"

    def test_start_task_agent_cleans_up_worktree_on_sdk_failure(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        runner.set_async_error(RuntimeError("SDK crashed"))
        executor = _make_executor(repo, runner, max_retries=0)
        _create_branch(repo, TASK_BRANCH)

        with pytest.raises(RuntimeError, match="SDK crashed"):
            executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        worktrees = _worktree_paths(repo)
        assert len(worktrees) == 1  # only main repo, worktree cleaned up


class TestModelSelection:
    def test_model_passed_to_sdk_for_async_agent(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(
            branch=TASK_BRANCH, prompt="Work", model="claude-sonnet-4-6"
        )

        assert runner.async_calls[0]["model"] == "claude-sonnet-4-6"

    def test_model_none_uses_sdk_default(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        assert runner.async_calls[0]["model"] is None

    def test_model_passed_to_sdk_for_sync_agent(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        runner.set_sync_result(json.dumps([]))
        executor = _make_executor(repo, runner)

        executor.run_decomposition(prompt="Decompose", model="claude-sonnet-4-6")

        assert runner.sync_calls[0]["model"] == "claude-sonnet-4-6"


class TestSyncTemporaryWorkspace:
    def test_run_decomposition_creates_and_cleans_up_temp_workspace(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        runner.set_sync_result(json.dumps([]))
        executor = _make_executor(repo, runner)

        executor.run_decomposition(prompt="Decompose")

        worktrees = _worktree_paths(repo)
        assert len(worktrees) == 1  # only main repo remains

    def test_run_decomposition_agent_runs_in_temp_worktree(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        runner.set_sync_result(json.dumps([]))
        executor = _make_executor(repo, runner)

        executor.run_decomposition(prompt="Decompose")

        assert len(runner.sync_calls) == 1
        cwd = runner.sync_calls[0]["cwd"]
        assert isinstance(cwd, Path)
        assert cwd != repo

    def test_run_decomposition_cleans_up_temp_branch(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        runner.set_sync_result(json.dumps([]))
        executor = _make_executor(repo, runner)

        executor.run_decomposition(prompt="Decompose")

        result = _git(repo, "branch", "--list", "hyperloop-tmp-*")
        assert result.stdout.strip() == ""
        result = _git(repo, "branch", "--list", "*-tmp-*")
        assert result.stdout.strip() == ""

    def test_run_decomposition_returns_parsed_tasks(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        tasks_json = json.dumps(
            [
                {
                    "name": "Task 1",
                    "description": "Do X",
                    "spec_path": "specs/foo.md",
                    "spec_blob_sha": "abc123",
                    "depends_on": [],
                },
                {
                    "name": "Task 2",
                    "description": "Do Y",
                    "spec_path": "specs/bar.md",
                    "spec_blob_sha": "def456",
                    "depends_on": ["Task 1"],
                },
            ]
        )
        runner.set_sync_result(tasks_json)
        executor = _make_executor(repo, runner)

        result = executor.run_decomposition(prompt="Decompose")

        assert len(result) == 2
        assert result[0] == ProposedTask(
            name="Task 1",
            description="Do X",
            spec_path="specs/foo.md",
            spec_blob_sha="abc123",
            depends_on=[],
        )
        assert result[1].depends_on == ["Task 1"]

    def test_run_decomposition_cleans_up_on_sdk_error(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        runner.set_sync_error(RuntimeError("SDK crashed"))
        executor = _make_executor(repo, runner, max_retries=0)

        with pytest.raises(RuntimeError, match="SDK crashed"):
            executor.run_decomposition(prompt="Decompose")

        worktrees = _worktree_paths(repo)
        assert len(worktrees) == 1

    def test_resolve_merge_returns_true_on_success(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        runner.set_sync_result(json.dumps({"resolved": True}))
        executor = _make_executor(repo, runner)
        _create_branch(repo, "hyperloop/spec/abc123/task/1")
        _create_branch(repo, "hyperloop/spec/abc123/delivery")

        result = executor.resolve_merge(
            task_branch="hyperloop/spec/abc123/task/1",
            delivery_branch="hyperloop/spec/abc123/delivery",
            prompt="Resolve conflict",
        )

        assert result is True

    def test_resolve_merge_returns_false_on_failure(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        runner.set_sync_result(json.dumps({"resolved": False}))
        executor = _make_executor(repo, runner)
        _create_branch(repo, "hyperloop/spec/abc123/task/1")
        _create_branch(repo, "hyperloop/spec/abc123/delivery")

        result = executor.resolve_merge(
            task_branch="hyperloop/spec/abc123/task/1",
            delivery_branch="hyperloop/spec/abc123/delivery",
            prompt="Resolve conflict",
        )

        assert result is False

    def test_compose_summary_returns_parsed_summary(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        runner.set_sync_result(
            json.dumps({"title": "Add feature X", "body": "Implements X via Y"})
        )
        executor = _make_executor(repo, runner)

        result = executor.compose_summary(prompt="Summarize")

        assert result == IntegrationSummary(
            title="Add feature X", body="Implements X via Y"
        )

    def test_sync_operation_passes_timeout(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        runner.set_sync_result(json.dumps([]))
        executor = _make_executor(repo, runner, timeout_seconds=120)

        executor.run_decomposition(prompt="Decompose")

        assert runner.sync_calls[0]["timeout_seconds"] == 120


class TestStaleWorktreeDetection:
    def test_detect_stale_finds_worktrees_in_managed_directory(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)
        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        stale = executor.detect_stale()

        assert TASK_BRANCH in stale

    def test_detect_stale_returns_empty_when_no_worktrees(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)

        stale = executor.detect_stale()

        assert stale == []


class TestCancellation:
    def test_cancel_stops_sdk_session(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)
        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        executor.cancel(branch=TASK_BRANCH)

        assert len(runner.stopped_sessions) == 1

    def test_cancel_removes_worktree(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)
        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        executor.cancel(branch=TASK_BRANCH)

        worktrees = _worktree_paths(repo)
        assert len(worktrees) == 1  # only main repo

    def test_cancel_does_not_delete_git_branch(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)
        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        executor.cancel(branch=TASK_BRANCH)

        assert _branch_exists(repo, TASK_BRANCH)

    def test_cancel_is_idempotent(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)
        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        executor.cancel(branch=TASK_BRANCH)
        executor.cancel(branch=TASK_BRANCH)  # no error

    def test_cancel_unknown_branch_is_noop(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)

        executor.cancel(branch="nonexistent/branch")  # no error

    def test_cancel_removes_worktree_not_tracked_in_memory(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)
        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        fresh_executor = _make_executor(repo, FakeSDKRunner())
        fresh_executor.cancel(branch=TASK_BRANCH)

        worktrees = _worktree_paths(repo)
        assert len(worktrees) == 1  # only main repo


class TestRetryLogic:
    def test_retries_on_transient_failure(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        runner.set_transient_failures(2)
        runner.set_sync_result(json.dumps([]))
        executor = _make_executor(repo, runner, max_retries=3)

        result = executor.run_decomposition(prompt="Decompose")

        assert result == []
        assert len(runner.sync_calls) == 3  # 2 failures + 1 success

    def test_exhausted_retries_raises(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        runner.set_transient_failures(5)
        executor = _make_executor(repo, runner, max_retries=2)

        with pytest.raises(ConnectionError):
            executor.run_decomposition(prompt="Decompose")

    def test_timeout_error_not_retried(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        runner.set_sync_error(ExecutorTimeoutError("timed out"))
        executor = _make_executor(repo, runner, max_retries=3)

        with pytest.raises(ExecutorTimeoutError):
            executor.run_decomposition(prompt="Decompose")

        assert len(runner.sync_calls) == 1  # no retries

    def test_retries_async_agent_start_on_transient_failure(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        runner.set_transient_failures(1)
        executor = _make_executor(repo, runner, max_retries=3)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        assert len(runner.async_calls) == 2  # 1 failure + 1 success


class TestEnvironmentIsolation:
    def test_strips_git_environment_variables(
        self, git_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        monkeypatch.setenv("GIT_DIR", "/some/dir")
        monkeypatch.setenv("GIT_INDEX_FILE", "/some/index")
        monkeypatch.setenv("GIT_WORK_TREE", "/some/tree")
        monkeypatch.setenv("GIT_COMMON_DIR", "/some/common")
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", "/some/ceiling")

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        env = runner.async_calls[0]["env"]
        assert isinstance(env, dict)
        assert "GIT_DIR" not in env
        assert "GIT_INDEX_FILE" not in env
        assert "GIT_WORK_TREE" not in env
        assert "GIT_COMMON_DIR" not in env
        assert "GIT_CEILING_DIRECTORIES" not in env

    def test_preserves_non_git_environment_variables(
        self, git_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        monkeypatch.setenv("HOME", "/home/test")
        monkeypatch.setenv("PATH", "/usr/bin:/usr/local/bin")

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        env = runner.async_calls[0]["env"]
        assert isinstance(env, dict)
        assert env["ANTHROPIC_API_KEY"] == "sk-test-key"
        assert env["HOME"] == "/home/test"
        assert "PATH" in env

    def test_sync_operations_also_strip_git_vars(
        self, git_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        runner.set_sync_result(json.dumps([]))
        executor = _make_executor(repo, runner)

        monkeypatch.setenv("GIT_DIR", "/some/dir")

        executor.run_decomposition(prompt="Decompose")

        env = runner.sync_calls[0]["env"]
        assert isinstance(env, dict)
        assert "GIT_DIR" not in env


class TestParallelIsolation:
    def test_two_agents_get_separate_worktrees(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakeSDKRunner()
        executor = _make_executor(repo, runner)
        branch_a = "hyperloop/spec/abc123/task/1"
        branch_b = "hyperloop/spec/abc123/task/2"
        _create_branch(repo, branch_a)
        _create_branch(repo, branch_b)

        executor.start_task_agent(branch=branch_a, prompt="Work A")
        executor.start_task_agent(branch=branch_b, prompt="Work B")

        cwd_a = runner.async_calls[0]["cwd"]
        cwd_b = runner.async_calls[1]["cwd"]
        assert cwd_a != cwd_b
        worktrees = _worktree_paths(repo)
        assert len(worktrees) == 3  # main + 2 agents
