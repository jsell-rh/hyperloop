from __future__ import annotations

import subprocess
from pathlib import Path

from hyperloop.reconciliation.adapters.git_agent_runtime import GitAgentRuntime
from hyperloop.reconciliation.models.agent_handle import AgentHandle
from hyperloop.reconciliation.models.poll_result import (
    AgentStatus,
    AgentVerdict,
    PollResult,
)
from hyperloop.reconciliation.models.integration_summary import IntegrationSummary
from hyperloop.reconciliation.models.proposed_task import ProposedTask
from hyperloop.reconciliation.models.spec_diff import SpecDiff
from hyperloop.reconciliation.models.task_briefing import TaskBriefing

from tests.reconciliation.fakes.fake_agent_executor import FakeAgentExecutor


def _git(
    repo: Path, *args: str, input: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        input=input,
        check=True,
    )


def _create_branch_from(repo: Path, branch: str, source: str) -> None:
    _git(repo, "branch", branch, source)


def _create_work_commit(repo: Path, branch: str, message: str) -> None:
    _git(repo, "checkout", branch)
    file_path = repo / "work.txt"
    file_path.write_text(message)
    _git(repo, "add", "work.txt")
    _git(repo, "commit", "-m", message)
    _git(repo, "checkout", "main")


def _create_signal_commit(repo: Path, branch: str, message: str) -> None:
    _git(repo, "checkout", branch)
    _git(repo, "commit", "--allow-empty", "-m", message)
    _git(repo, "checkout", "main")


def _push_branch(repo: Path, branch: str) -> None:
    _git(repo, "push", "origin", branch)


BRANCH_PREFIX = "hyperloop/"
BLOB_SHA = "abc123"
TASK_BRANCH = f"{BRANCH_PREFIX}spec/{BLOB_SHA}/task/5"
VERIFIER_BRANCH = f"{BRANCH_PREFIX}spec/{BLOB_SHA}/verifier"


def _make_runtime(
    repo_path: Path,
    executor: FakeAgentExecutor | None = None,
) -> GitAgentRuntime:
    return GitAgentRuntime(
        repo_path,
        branch_prefix=BRANCH_PREFIX,
        executor=executor or FakeAgentExecutor(),
        remote="origin",
    )


class TestPollRunningTask:
    def test_returns_running_when_latest_commit_has_file_changes(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        _create_branch_from(local, TASK_BRANCH, "main")
        _create_work_commit(local, TASK_BRANCH, "Implement login endpoint")
        _push_branch(local, TASK_BRANCH)

        runtime = _make_runtime(local)
        handle = AgentHandle(id=TASK_BRANCH)
        result = runtime.poll(handle)

        assert result.status == AgentStatus.RUNNING
        assert result.rationale is None
        assert result.verdict is None

    def test_returns_running_when_empty_commit_has_no_trailer(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        _create_branch_from(local, TASK_BRANCH, "main")
        _create_signal_commit(local, TASK_BRANCH, "WIP: still working on it")
        _push_branch(local, TASK_BRANCH)

        runtime = _make_runtime(local)
        handle = AgentHandle(id=TASK_BRANCH)
        result = runtime.poll(handle)

        assert result.status == AgentStatus.RUNNING


class TestPollCompletedTask:
    def test_returns_complete_with_rationale(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _create_branch_from(local, TASK_BRANCH, "main")
        _create_work_commit(local, TASK_BRANCH, "Implement login endpoint")
        _create_signal_commit(
            local,
            TASK_BRANCH,
            "Implemented login endpoint with JWT validation\n\nTask-Status: Complete",
        )
        _push_branch(local, TASK_BRANCH)

        runtime = _make_runtime(local)
        handle = AgentHandle(id=TASK_BRANCH)
        result = runtime.poll(handle)

        assert result.status == AgentStatus.COMPLETE
        assert result.rationale is not None
        assert "Implemented login endpoint" in result.rationale
        assert result.verdict is None

    def test_preserves_multiline_rationale(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _create_branch_from(local, TASK_BRANCH, "main")
        _create_signal_commit(
            local,
            TASK_BRANCH,
            "Implemented login endpoint\n\nAlso added input validation\nand rate limiting\n\nTask-Status: Complete",
        )
        _push_branch(local, TASK_BRANCH)

        runtime = _make_runtime(local)
        handle = AgentHandle(id=TASK_BRANCH)
        result = runtime.poll(handle)

        assert result.status == AgentStatus.COMPLETE
        assert result.rationale is not None
        assert "input validation" in result.rationale
        assert "rate limiting" in result.rationale


class TestPollFailedTask:
    def test_returns_failed_with_rationale(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _create_branch_from(local, TASK_BRANCH, "main")
        _create_signal_commit(
            local,
            TASK_BRANCH,
            "Could not resolve dependency conflict\n\nTask-Status: Failed",
        )
        _push_branch(local, TASK_BRANCH)

        runtime = _make_runtime(local)
        handle = AgentHandle(id=TASK_BRANCH)
        result = runtime.poll(handle)

        assert result.status == AgentStatus.FAILED
        assert result.rationale is not None
        assert "dependency conflict" in result.rationale


class TestPollVerificationPass:
    def test_returns_complete_with_pass_verdict(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        _create_branch_from(local, VERIFIER_BRANCH, "main")
        _create_signal_commit(
            local,
            VERIFIER_BRANCH,
            "All requirements verified against implementation\n\nVerification-Status: Pass",
        )
        _push_branch(local, VERIFIER_BRANCH)

        runtime = _make_runtime(local)
        handle = AgentHandle(id=VERIFIER_BRANCH)
        result = runtime.poll(handle)

        assert result.status == AgentStatus.COMPLETE
        assert result.verdict == AgentVerdict.PASS
        assert result.rationale is not None
        assert "requirements verified" in result.rationale


class TestPollVerificationFail:
    def test_returns_complete_with_fail_verdict_not_failed_status(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        _create_branch_from(local, VERIFIER_BRANCH, "main")
        _create_signal_commit(
            local,
            VERIFIER_BRANCH,
            "Missing input validation on user endpoint\n\nVerification-Status: Fail",
        )
        _push_branch(local, VERIFIER_BRANCH)

        runtime = _make_runtime(local)
        handle = AgentHandle(id=VERIFIER_BRANCH)
        result = runtime.poll(handle)

        assert result.status == AgentStatus.COMPLETE
        assert result.verdict == AgentVerdict.FAIL
        assert result.status != AgentStatus.FAILED
        assert result.rationale is not None
        assert "input validation" in result.rationale


class TestPollFetchesRemote:
    def test_poll_detects_remote_completion_signal(
        self, git_env: tuple[Path, Path], tmp_path: Path
    ) -> None:
        local, remote = git_env

        _create_branch_from(local, TASK_BRANCH, "main")
        _create_work_commit(local, TASK_BRANCH, "Initial work")
        _push_branch(local, TASK_BRANCH)

        agent_clone = tmp_path / "agent"
        subprocess.run(
            ["git", "clone", str(remote), str(agent_clone)],
            check=True,
            capture_output=True,
        )
        _git(agent_clone, "config", "user.name", "Agent")
        _git(agent_clone, "config", "user.email", "agent@example.com")
        _git(agent_clone, "checkout", TASK_BRANCH)
        _git(
            agent_clone,
            "commit",
            "--allow-empty",
            "-m",
            "Work complete\n\nTask-Status: Complete",
        )
        _git(agent_clone, "push", "origin", TASK_BRANCH)

        runtime = _make_runtime(local)
        handle = AgentHandle(id=TASK_BRANCH)
        result = runtime.poll(handle)

        assert result.status == AgentStatus.COMPLETE


class TestDetectOrphans:
    def test_finds_task_branches_without_completion_signal(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        branch_5 = f"hyperloop/spec/{BLOB_SHA}/task/5"
        branch_6 = f"hyperloop/spec/{BLOB_SHA}/task/6"

        _create_branch_from(local, branch_5, "main")
        _create_work_commit(local, branch_5, "Work on task 5")
        _push_branch(local, branch_5)

        _create_branch_from(local, branch_6, "main")
        _create_work_commit(local, branch_6, "Work on task 6")
        _push_branch(local, branch_6)

        runtime = _make_runtime(local)
        orphans = runtime.detect_orphans()

        orphan_ids = {h.id for h in orphans}
        assert branch_5 in orphan_ids
        assert branch_6 in orphan_ids

    def test_excludes_branches_with_complete_signal(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        branch_5 = f"hyperloop/spec/{BLOB_SHA}/task/5"
        branch_6 = f"hyperloop/spec/{BLOB_SHA}/task/6"

        _create_branch_from(local, branch_5, "main")
        _create_work_commit(local, branch_5, "Work on task 5")
        _create_signal_commit(local, branch_5, "Done\n\nTask-Status: Complete")
        _push_branch(local, branch_5)

        _create_branch_from(local, branch_6, "main")
        _create_work_commit(local, branch_6, "Work on task 6")
        _push_branch(local, branch_6)

        runtime = _make_runtime(local)
        orphans = runtime.detect_orphans()

        orphan_ids = {h.id for h in orphans}
        assert branch_5 not in orphan_ids
        assert branch_6 in orphan_ids

    def test_excludes_branches_with_failed_signal(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        branch_5 = f"hyperloop/spec/{BLOB_SHA}/task/5"
        branch_6 = f"hyperloop/spec/{BLOB_SHA}/task/6"

        _create_branch_from(local, branch_5, "main")
        _create_signal_commit(
            local, branch_5, "Could not complete\n\nTask-Status: Failed"
        )
        _push_branch(local, branch_5)

        _create_branch_from(local, branch_6, "main")
        _create_work_commit(local, branch_6, "Work on task 6")
        _push_branch(local, branch_6)

        runtime = _make_runtime(local)
        orphans = runtime.detect_orphans()

        orphan_ids = {h.id for h in orphans}
        assert branch_5 not in orphan_ids
        assert branch_6 in orphan_ids

    def test_finds_verifier_branches_without_signal(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        _create_branch_from(local, VERIFIER_BRANCH, "main")
        _create_work_commit(local, VERIFIER_BRANCH, "Checking specs")
        _push_branch(local, VERIFIER_BRANCH)

        runtime = _make_runtime(local)
        orphans = runtime.detect_orphans()

        orphan_ids = {h.id for h in orphans}
        assert VERIFIER_BRANCH in orphan_ids

    def test_returns_empty_when_no_hyperloop_branches(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        runtime = _make_runtime(local)
        orphans = runtime.detect_orphans()
        assert orphans == []

    def test_ignores_delivery_branches(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        delivery_branch = f"hyperloop/spec/{BLOB_SHA}"
        _create_branch_from(local, delivery_branch, "main")
        _push_branch(local, delivery_branch)

        runtime = _make_runtime(local)
        orphans = runtime.detect_orphans()

        orphan_ids = {h.id for h in orphans}
        assert delivery_branch not in orphan_ids

    def test_ignores_plan_branch(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _create_branch_from(local, "hyperloop/plan", "main")
        _push_branch(local, "hyperloop/plan")

        runtime = _make_runtime(local)
        orphans = runtime.detect_orphans()
        assert orphans == []

    def test_detects_orphans_pushed_by_other_clone(
        self, git_env: tuple[Path, Path], tmp_path: Path
    ) -> None:
        local, remote = git_env

        agent_clone = tmp_path / "agent"
        subprocess.run(
            ["git", "clone", str(remote), str(agent_clone)],
            check=True,
            capture_output=True,
        )
        _git(agent_clone, "config", "user.name", "Agent")
        _git(agent_clone, "config", "user.email", "agent@example.com")
        _git(agent_clone, "branch", TASK_BRANCH, "main")
        _create_work_commit(agent_clone, TASK_BRANCH, "Agent work")
        _push_branch(agent_clone, TASK_BRANCH)

        runtime = _make_runtime(local)
        orphans = runtime.detect_orphans()

        orphan_ids = {h.id for h in orphans}
        assert TASK_BRANCH in orphan_ids


class TestCancel:
    def test_deletes_local_branch(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _create_branch_from(local, TASK_BRANCH, "main")
        _push_branch(local, TASK_BRANCH)

        runtime = _make_runtime(local)
        handle = AgentHandle(id=TASK_BRANCH)
        runtime.cancel(handle)

        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/heads/{TASK_BRANCH}"],
            cwd=local,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_deletes_remote_branch(self, git_env: tuple[Path, Path]) -> None:
        local, remote = git_env
        _create_branch_from(local, TASK_BRANCH, "main")
        _push_branch(local, TASK_BRANCH)

        runtime = _make_runtime(local)
        handle = AgentHandle(id=TASK_BRANCH)
        runtime.cancel(handle)

        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/heads/{TASK_BRANCH}"],
            cwd=remote,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_cancel_is_idempotent(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _create_branch_from(local, TASK_BRANCH, "main")
        _push_branch(local, TASK_BRANCH)

        runtime = _make_runtime(local)
        handle = AgentHandle(id=TASK_BRANCH)
        runtime.cancel(handle)
        runtime.cancel(handle)


class TestCustomBranchPrefix:
    def test_poll_works_with_custom_prefix(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        prefix = "myloop/"
        branch = f"{prefix}spec/abc123/task/1"

        _create_branch_from(local, branch, "main")
        _create_signal_commit(local, branch, "Done\n\nTask-Status: Complete")
        _push_branch(local, branch)

        runtime = GitAgentRuntime(
            local, branch_prefix=prefix, executor=FakeAgentExecutor(), remote="origin"
        )
        result = runtime.poll(AgentHandle(id=branch))

        assert result.status == AgentStatus.COMPLETE

    def test_detect_orphans_uses_configured_prefix(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        prefix = "myloop/"
        branch = f"{prefix}spec/abc123/task/1"

        _create_branch_from(local, branch, "main")
        _create_work_commit(local, branch, "Work")
        _push_branch(local, branch)

        runtime = GitAgentRuntime(
            local, branch_prefix=prefix, executor=FakeAgentExecutor(), remote="origin"
        )
        orphans = runtime.detect_orphans()

        orphan_ids = {h.id for h in orphans}
        assert branch in orphan_ids

    def test_detect_orphans_ignores_other_prefixes(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        branch = f"{BRANCH_PREFIX}spec/abc123/task/1"
        _create_branch_from(local, branch, "main")
        _create_work_commit(local, branch, "Work")
        _push_branch(local, branch)

        runtime = GitAgentRuntime(
            local,
            branch_prefix="other/",
            executor=FakeAgentExecutor(),
            remote="origin",
        )
        orphans = runtime.detect_orphans()

        assert orphans == []


class TestLaunchTask:
    def test_returns_handle_with_branch_as_id(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _create_branch_from(local, TASK_BRANCH, "main")

        executor = FakeAgentExecutor()
        runtime = _make_runtime(local, executor)
        briefing = TaskBriefing(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            task_description="Implement auth endpoint",
            workspace_id=f"task/{BLOB_SHA}/5",
        )

        handle = runtime.launch_task(briefing)

        assert handle.id == TASK_BRANCH

    def test_delegates_to_executor_with_branch_and_briefing(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        _create_branch_from(local, TASK_BRANCH, "main")

        executor = FakeAgentExecutor()
        runtime = _make_runtime(local, executor)
        briefing = TaskBriefing(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            task_description="Implement auth endpoint",
            workspace_id=f"task/{BLOB_SHA}/5",
        )

        runtime.launch_task(briefing)

        assert len(executor.started_tasks) == 1
        branch, received_briefing = executor.started_tasks[0]
        assert branch == TASK_BRANCH
        assert received_briefing is briefing

    def test_handle_is_pollable(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _create_branch_from(local, TASK_BRANCH, "main")
        _create_work_commit(local, TASK_BRANCH, "Agent work")
        _push_branch(local, TASK_BRANCH)

        runtime = _make_runtime(local)
        briefing = TaskBriefing(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            task_description="Implement auth endpoint",
            workspace_id=f"task/{BLOB_SHA}/5",
        )

        handle = runtime.launch_task(briefing)
        result = runtime.poll(handle)

        assert result.status == AgentStatus.RUNNING

    def test_uses_configured_branch_prefix(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        prefix = "myloop/"
        branch = f"{prefix}spec/{BLOB_SHA}/task/5"
        _create_branch_from(local, branch, "main")

        executor = FakeAgentExecutor()
        runtime = GitAgentRuntime(
            local, branch_prefix=prefix, executor=executor, remote="origin"
        )
        briefing = TaskBriefing(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            task_description="Implement auth endpoint",
            workspace_id=f"task/{BLOB_SHA}/5",
        )

        handle = runtime.launch_task(briefing)

        assert handle.id == branch

    def test_executor_failure_propagates(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _create_branch_from(local, TASK_BRANCH, "main")

        executor = FakeAgentExecutor()
        executor.set_start_task_error(RuntimeError("Agent start failed"))
        runtime = _make_runtime(local, executor)
        briefing = TaskBriefing(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            task_description="Implement auth endpoint",
            workspace_id=f"task/{BLOB_SHA}/5",
        )

        try:
            runtime.launch_task(briefing)
            assert False, "Expected RuntimeError"
        except RuntimeError as exc:
            assert "Agent start failed" in str(exc)

    def test_unknown_workspace_type_raises_value_error(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        runtime = _make_runtime(local)
        briefing = TaskBriefing(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            task_description="Implement auth endpoint",
            workspace_id=f"unknown/{BLOB_SHA}/5",
        )

        try:
            runtime.launch_task(briefing)
            assert False, "Expected ValueError"
        except ValueError as exc:
            assert "Unknown workspace type" in str(exc)


class TestLaunchDecomposition:
    def test_returns_proposed_tasks_from_executor(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        expected = [
            ProposedTask(
                name="implement-auth",
                description="Add auth endpoint",
                spec_path="specs/auth.spec.md",
                spec_blob_sha=BLOB_SHA,
            ),
        ]
        executor = FakeAgentExecutor()
        executor.set_decomposition_result(expected)
        runtime = _make_runtime(local, executor)

        spec_diffs = [
            SpecDiff(
                spec_path="specs/auth.spec.md",
                blob_sha=BLOB_SHA,
                diff_text="+ new requirement",
            ),
        ]
        result = runtime.launch_decomposition(spec_diffs, [], [])

        assert result == expected

    def test_passes_all_parameters_to_executor(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        executor = FakeAgentExecutor()
        runtime = _make_runtime(local, executor)

        spec_diffs = [
            SpecDiff(
                spec_path="specs/auth.spec.md",
                blob_sha=BLOB_SHA,
                diff_text="+ new requirement",
            ),
        ]
        runtime.launch_decomposition(spec_diffs, [], [])

        assert len(executor.decomposition_calls) == 1
        received_diffs, received_tasks, received_events = executor.decomposition_calls[
            0
        ]
        assert received_diffs == spec_diffs
        assert received_tasks == []
        assert received_events == []

    def test_executor_failure_propagates(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        executor = FakeAgentExecutor()
        executor.set_decomposition_error(RuntimeError("LLM unavailable"))
        runtime = _make_runtime(local, executor)

        spec_diffs = [
            SpecDiff(
                spec_path="specs/auth.spec.md",
                blob_sha=BLOB_SHA,
                diff_text="+ new requirement",
            ),
        ]

        try:
            runtime.launch_decomposition(spec_diffs, [], [])
            assert False, "Expected RuntimeError"
        except RuntimeError as exc:
            assert "LLM unavailable" in str(exc)


class TestLaunchVerification:
    def test_returns_handle_with_verifier_branch_as_id(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        _create_branch_from(local, VERIFIER_BRANCH, "main")

        executor = FakeAgentExecutor()
        runtime = _make_runtime(local, executor)

        handle = runtime.launch_verification(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            workspace_id=f"verification/{BLOB_SHA}",
        )

        assert handle.id == VERIFIER_BRANCH

    def test_delegates_to_executor(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _create_branch_from(local, VERIFIER_BRANCH, "main")

        executor = FakeAgentExecutor()
        runtime = _make_runtime(local, executor)

        runtime.launch_verification(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            workspace_id=f"verification/{BLOB_SHA}",
        )

        assert len(executor.started_verifications) == 1
        branch, content, path, sha = executor.started_verifications[0]
        assert branch == VERIFIER_BRANCH
        assert content == "# Auth Spec"
        assert path == "specs/auth.spec.md"
        assert sha == BLOB_SHA

    def test_handle_is_pollable(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _create_branch_from(local, VERIFIER_BRANCH, "main")
        _create_signal_commit(
            local,
            VERIFIER_BRANCH,
            "All verified\n\nVerification-Status: Pass",
        )
        _push_branch(local, VERIFIER_BRANCH)

        runtime = _make_runtime(local)
        handle = runtime.launch_verification(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            workspace_id=f"verification/{BLOB_SHA}",
        )
        result = runtime.poll(handle)

        assert result.status == AgentStatus.COMPLETE
        assert result.verdict == AgentVerdict.PASS

    def test_executor_failure_propagates(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env

        executor = FakeAgentExecutor()
        executor.set_start_verification_error(RuntimeError("Verification start failed"))
        runtime = _make_runtime(local, executor)

        try:
            runtime.launch_verification(
                spec_content="# Auth Spec",
                spec_path="specs/auth.spec.md",
                spec_blob_sha=BLOB_SHA,
                workspace_id=f"verification/{BLOB_SHA}",
            )
            assert False, "Expected RuntimeError"
        except RuntimeError as exc:
            assert "Verification start failed" in str(exc)


class TestLaunchMergeResolution:
    def test_delegates_to_executor_with_branch_names(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        executor = FakeAgentExecutor()
        runtime = _make_runtime(local, executor)

        result = runtime.launch_merge_resolution(
            task_workspace_id=f"task/{BLOB_SHA}/5",
            delivery_workspace_id=f"delivery/{BLOB_SHA}",
            conflict_details="Conflict in auth.py",
        )

        assert result is True
        assert len(executor.merge_calls) == 1
        task_br, delivery_br, details = executor.merge_calls[0]
        assert task_br == TASK_BRANCH
        assert delivery_br == f"{BRANCH_PREFIX}spec/{BLOB_SHA}/delivery"
        assert details == "Conflict in auth.py"

    def test_returns_false_on_failure(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        executor = FakeAgentExecutor()
        executor.set_merge_result(False)
        runtime = _make_runtime(local, executor)

        result = runtime.launch_merge_resolution(
            task_workspace_id=f"task/{BLOB_SHA}/5",
            delivery_workspace_id=f"delivery/{BLOB_SHA}",
            conflict_details="Conflict in auth.py",
        )

        assert result is False


class TestComposeIntegrationSummary:
    def test_delegates_to_executor(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        expected = IntegrationSummary(title="Add auth", body="Implements auth spec")
        executor = FakeAgentExecutor()
        executor.set_integration_summary(expected)
        runtime = _make_runtime(local, executor)

        result = runtime.compose_integration_summary(
            spec_content="# Auth Spec",
            task_summaries=[("implement-auth", "Added auth endpoint")],
            verification_rationale="All requirements met",
        )

        assert result == expected
        assert len(executor.summary_calls) == 1
        content, summaries, rationale = executor.summary_calls[0]
        assert content == "# Auth Spec"
        assert summaries == [("implement-auth", "Added auth endpoint")]
        assert rationale == "All requirements met"

    def test_executor_failure_propagates(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        executor = FakeAgentExecutor()
        executor.set_integration_summary_error(RuntimeError("LLM unavailable"))
        runtime = _make_runtime(local, executor)

        try:
            runtime.compose_integration_summary(
                spec_content="# Auth Spec",
                task_summaries=[],
                verification_rationale="All requirements met",
            )
            assert False, "Expected RuntimeError"
        except RuntimeError as exc:
            assert "LLM unavailable" in str(exc)


class TestProtocolConformance:
    def test_has_poll_method(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitAgentRuntime.poll)
        assert hints["handle"] is AgentHandle
        assert hints["return"] is PollResult

    def test_has_cancel_method(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitAgentRuntime.cancel)
        assert hints["handle"] is AgentHandle
        assert hints["return"] is type(None)

    def test_has_detect_orphans_method(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitAgentRuntime.detect_orphans)
        assert hints["return"] == list[AgentHandle]

    def test_has_launch_task_method(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitAgentRuntime.launch_task)
        assert hints["briefing"] is TaskBriefing
        assert hints["return"] is AgentHandle

    def test_has_launch_decomposition_method(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitAgentRuntime.launch_decomposition)
        assert hints["spec_diffs"] == list[SpecDiff]
        assert hints["return"] == list[ProposedTask]

    def test_has_launch_verification_method(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitAgentRuntime.launch_verification)
        assert hints["spec_content"] is str
        assert hints["return"] is AgentHandle

    def test_has_launch_merge_resolution_method(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitAgentRuntime.launch_merge_resolution)
        assert hints["conflict_details"] is str
        assert hints["return"] is bool

    def test_has_compose_integration_summary_method(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitAgentRuntime.compose_integration_summary)
        assert hints["spec_content"] is str
        assert hints["return"] is IntegrationSummary

    def test_adapter_imports_from_domain(self) -> None:
        import inspect

        import hyperloop.reconciliation.adapters.git_agent_runtime as module

        source = inspect.getsource(module)
        assert "hyperloop.reconciliation.models" in source
