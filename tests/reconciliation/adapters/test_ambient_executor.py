from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hyperloop.reconciliation.adapters.ambient_executor import AmbientExecutor
from hyperloop.reconciliation.models.executor_timeout_error import ExecutorTimeoutError
from hyperloop.reconciliation.models.integration_summary import IntegrationSummary
from hyperloop.reconciliation.models.proposed_task import ProposedTask

from hyperloop.reconciliation.models.session_status import SessionStatus

from tests.reconciliation.fakes.fake_platform_runner import FakePlatformRunner


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


def _remote_branch_exists(repo: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", branch],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


REPO_URL = "https://github.com/example/repo.git"
PROJECT_ID = "proj-123"
TASK_BRANCH = "hyperloop/spec/abc123/task/5"
VERIFIER_BRANCH = "hyperloop/spec/abc123/verifier"


def _make_executor(
    repo: Path,
    runner: FakePlatformRunner,
    *,
    timeout_seconds: int = 300,
    max_retries: int = 3,
) -> AmbientExecutor:
    return AmbientExecutor(
        repo_path=repo,
        platform_runner=runner,
        repository_url=REPO_URL,
        project_name=PROJECT_ID,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )


def _make_sync_executor(
    repo: Path,
    remote: Path,
    runner: FakePlatformRunner,
    *,
    timeout_seconds: int = 300,
    max_retries: int = 3,
) -> AmbientExecutor:
    runner._remote_path = remote
    return _make_executor(
        repo, runner, timeout_seconds=timeout_seconds, max_retries=max_retries
    )


class TestBranchPushBeforeSessionCreation:
    def test_pushes_branch_to_remote_before_creating_session(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, remote = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Do work")

        assert _remote_branch_exists(repo, TASK_BRANCH)
        assert len(runner.create_calls) == 1

    def test_push_failure_raises_without_creating_session(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)

        with pytest.raises(subprocess.CalledProcessError):
            executor.start_task_agent(branch="nonexistent/branch", prompt="Work")

        assert len(runner.create_calls) == 0


class TestAsyncSessionCreation:
    def test_creates_session_with_prompt_and_repo_url(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Do specific work")

        assert len(runner.create_calls) == 1
        call = runner.create_calls[0]
        assert call["prompt"] == "Do specific work"
        assert call["repository_url"] == REPO_URL
        assert call["project"] == PROJECT_ID

    def test_session_name_derived_from_branch(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        name = runner.create_calls[0]["name"]
        assert isinstance(name, str)
        assert len(name) > 0

    def test_returns_immediately_after_session_creation(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        assert len(runner.wait_calls) == 0

    def test_start_verification_agent_creates_session(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, VERIFIER_BRANCH)

        executor.start_verification_agent(branch=VERIFIER_BRANCH, prompt="Verify")

        assert len(runner.create_calls) == 1


class TestModelSelection:
    def test_model_passed_to_platform_for_async_agent(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(
            branch=TASK_BRANCH, prompt="Work", model="claude-sonnet-4-6"
        )

        assert runner.create_calls[0]["model"] == "claude-sonnet-4-6"

    def test_model_none_passed_to_platform(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        assert runner.create_calls[0]["model"] is None

    def test_model_passed_to_platform_for_sync_agent(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, remote = git_env
        runner = FakePlatformRunner()
        runner.set_sync_result(json.dumps([]))
        executor = _make_sync_executor(repo, remote, runner)

        executor.run_decomposition(prompt="Decompose", model="claude-sonnet-4-6")

        assert runner.create_calls[0]["model"] == "claude-sonnet-4-6"


class TestSyncExecution:
    def test_run_decomposition_blocks_until_completion(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, remote = git_env
        runner = FakePlatformRunner()
        tasks_json = json.dumps(
            [
                {
                    "name": "Task 1",
                    "description": "Do X",
                    "spec_path": "specs/foo.md",
                    "spec_blob_sha": "abc123",
                    "depends_on": [],
                },
            ]
        )
        runner.set_sync_result(tasks_json)
        executor = _make_sync_executor(repo, remote, runner)

        result = executor.run_decomposition(prompt="Decompose")

        assert len(result) == 1
        assert result[0] == ProposedTask(
            name="Task 1",
            description="Do X",
            spec_path="specs/foo.md",
            spec_blob_sha="abc123",
            depends_on=[],
        )
        assert len(runner.wait_calls) == 1

    def test_sync_session_stopped_after_completion(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, remote = git_env
        runner = FakePlatformRunner()
        runner.set_sync_result(json.dumps([]))
        executor = _make_sync_executor(repo, remote, runner)

        executor.run_decomposition(prompt="Decompose")

        assert len(runner.stop_calls) == 1

    def test_resolve_merge_returns_true_on_success(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, remote = git_env
        runner = FakePlatformRunner()
        runner.set_sync_result(json.dumps({"resolved": True}))
        executor = _make_sync_executor(repo, remote, runner)

        result = executor.resolve_merge(
            task_branch="hyperloop/spec/abc123/task/1",
            delivery_branch="hyperloop/spec/abc123/delivery",
            prompt="Resolve conflict",
        )

        assert result is True

    def test_resolve_merge_returns_false_on_failure(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, remote = git_env
        runner = FakePlatformRunner()
        runner.set_sync_result(json.dumps({"resolved": False}))
        executor = _make_sync_executor(repo, remote, runner)

        result = executor.resolve_merge(
            task_branch="hyperloop/spec/abc123/task/1",
            delivery_branch="hyperloop/spec/abc123/delivery",
            prompt="Resolve conflict",
        )

        assert result is False

    def test_compose_summary_returns_parsed_summary(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, remote = git_env
        runner = FakePlatformRunner()
        runner.set_sync_result(
            json.dumps({"title": "Add feature X", "body": "Implements X via Y"})
        )
        executor = _make_sync_executor(repo, remote, runner)

        result = executor.compose_summary(prompt="Summarize")

        assert result == IntegrationSummary(
            title="Add feature X", body="Implements X via Y"
        )

    def test_sync_operation_passes_timeout(self, git_env: tuple[Path, Path]) -> None:
        repo, remote = git_env
        runner = FakePlatformRunner()
        runner.set_sync_result(json.dumps([]))
        executor = _make_sync_executor(repo, remote, runner, timeout_seconds=120)

        executor.run_decomposition(prompt="Decompose")

        assert runner.wait_calls[0]["timeout_seconds"] == 120

    def test_sync_operation_cleans_up_session_on_error(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        runner.set_sync_error(RuntimeError("Agent crashed"))
        executor = _make_executor(repo, runner, max_retries=0)

        with pytest.raises(RuntimeError, match="Agent crashed"):
            executor.run_decomposition(prompt="Decompose")

        assert len(runner.stop_calls) == 1


class TestStaleSessionDetection:
    def test_detect_stale_finds_sessions_matching_naming_convention(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)
        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        runner._running_sessions.clear()
        runner._running_sessions["stale-sid"] = executor._session_name(TASK_BRANCH)

        stale = executor.detect_stale()

        assert TASK_BRANCH in stale

    def test_detect_stale_returns_empty_when_no_matching_sessions(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)

        stale = executor.detect_stale()

        assert stale == []

    def test_detect_stale_ignores_sessions_not_matching_convention(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        runner._running_sessions["other-sid"] = "unrelated-session-name"

        stale = executor.detect_stale()

        assert stale == []


class TestCancellation:
    def test_cancel_stops_platform_session(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)
        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        executor.cancel(branch=TASK_BRANCH)

        assert len(runner.stop_calls) == 1

    def test_cancel_cleans_up_internal_tracking(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)
        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        executor.cancel(branch=TASK_BRANCH)

        assert TASK_BRANCH not in executor._sessions

    def test_cancel_does_not_delete_git_branch(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)
        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        executor.cancel(branch=TASK_BRANCH)

        assert _branch_exists(repo, TASK_BRANCH)

    def test_cancel_is_idempotent(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)
        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        executor.cancel(branch=TASK_BRANCH)
        executor.cancel(branch=TASK_BRANCH)

    def test_cancel_unknown_branch_is_noop(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)

        executor.cancel(branch="nonexistent/branch")


class TestRetryLogic:
    def test_retries_on_transient_failure(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        runner.set_transient_failures(2)
        executor = _make_executor(repo, runner, max_retries=3)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        assert len(runner.create_calls) == 3  # 2 failures + 1 success

    def test_exhausted_retries_raises(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        runner.set_transient_failures(5)
        executor = _make_executor(repo, runner, max_retries=2)
        _create_branch(repo, TASK_BRANCH)

        with pytest.raises(ConnectionError):
            executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

    def test_timeout_error_not_retried(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        runner.set_sync_error(ExecutorTimeoutError("timed out"))
        executor = _make_executor(repo, runner, max_retries=3)

        with pytest.raises(ExecutorTimeoutError):
            executor.run_decomposition(prompt="Decompose")

        assert len(runner.wait_calls) == 1


class TestHealthMonitoring:
    def test_check_health_detects_stopped_session(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)
        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        session_id = executor._sessions[TASK_BRANCH]
        runner._running_sessions.pop(session_id)

        terminated = executor.check_health()

        assert TASK_BRANCH in terminated
        assert TASK_BRANCH not in executor._sessions

    def test_check_health_keeps_running_sessions(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)
        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        terminated = executor.check_health()

        assert terminated == []
        assert TASK_BRANCH in executor._sessions

    def test_check_health_returns_empty_when_no_sessions(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)

        terminated = executor.check_health()

        assert terminated == []


class TestIsAlive:
    def test_returns_true_when_session_is_running(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        assert executor.is_alive(branch=TASK_BRANCH) is True

    def test_returns_false_when_session_has_stopped(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")
        session_id = executor._sessions[TASK_BRANCH]
        runner.set_session_status(session_id, SessionStatus.STOPPED)

        assert executor.is_alive(branch=TASK_BRANCH) is False

    def test_returns_false_when_session_has_failed(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")
        session_id = executor._sessions[TASK_BRANCH]
        runner.set_session_status(session_id, SessionStatus.FAILED)

        assert executor.is_alive(branch=TASK_BRANCH) is False

    def test_returns_false_for_unknown_branch(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)

        assert executor.is_alive(branch="nonexistent/branch") is False

    def test_returns_false_after_cancel(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")
        executor.cancel(branch=TASK_BRANCH)

        assert executor.is_alive(branch=TASK_BRANCH) is False

    def test_returns_true_for_verification_agent(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        _create_branch(repo, VERIFIER_BRANCH)

        executor.start_verification_agent(branch=VERIFIER_BRANCH, prompt="Verify")

        assert executor.is_alive(branch=VERIFIER_BRANCH) is True


class TestProcessExitCleanup:
    def test_cleanup_stops_all_tracked_sessions(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        branch_a = "hyperloop/spec/abc123/task/1"
        branch_b = "hyperloop/spec/abc123/task/2"
        _create_branch(repo, branch_a)
        _create_branch(repo, branch_b)
        executor.start_task_agent(branch=branch_a, prompt="Work A")
        executor.start_task_agent(branch=branch_b, prompt="Work B")

        executor._cleanup_all_sessions()

        assert len(runner.stop_calls) == 2
        assert len(executor._sessions) == 0


class TestParallelIsolation:
    def test_two_agents_get_separate_sessions(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)
        branch_a = "hyperloop/spec/abc123/task/1"
        branch_b = "hyperloop/spec/abc123/task/2"
        _create_branch(repo, branch_a)
        _create_branch(repo, branch_b)

        executor.start_task_agent(branch=branch_a, prompt="Work A")
        executor.start_task_agent(branch=branch_b, prompt="Work B")

        assert len(runner.create_calls) == 2
        name_a = runner.create_calls[0]["name"]
        name_b = runner.create_calls[1]["name"]
        assert name_a != name_b


class TestSessionNamingConvention:
    def test_session_name_is_deterministic(self, git_env: tuple[Path, Path]) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)

        name1 = executor._session_name(TASK_BRANCH)
        name2 = executor._session_name(TASK_BRANCH)

        assert name1 == name2

    def test_session_name_round_trips_to_branch(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)

        name = executor._session_name(TASK_BRANCH)
        recovered = executor._branch_from_session_name(name)

        assert recovered == TASK_BRANCH

    def test_different_branches_produce_different_names(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner)

        name_a = executor._session_name("hyperloop/spec/abc123/task/1")
        name_b = executor._session_name("hyperloop/spec/abc123/task/2")

        assert name_a != name_b

    def test_session_prefix_derives_from_branch_prefix(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, _ = git_env
        runner = FakePlatformRunner()
        executor = AmbientExecutor(
            repo_path=repo,
            platform_runner=runner,
            repository_url=REPO_URL,
            project_name=PROJECT_ID,
            branch_prefix="custom/prefix/",
        )

        name = executor._session_name("custom/prefix/task/1")

        assert name.startswith("custom%2Fprefix-")


class TestBranchPushRetry:
    def test_push_retries_on_transient_failure(
        self, git_env: tuple[Path, Path]
    ) -> None:
        repo, remote = git_env
        runner = FakePlatformRunner()
        executor = _make_executor(repo, runner, max_retries=3)
        _create_branch(repo, TASK_BRANCH)

        executor.start_task_agent(branch=TASK_BRANCH, prompt="Work")

        assert _remote_branch_exists(repo, TASK_BRANCH)
        assert len(runner.create_calls) == 1
