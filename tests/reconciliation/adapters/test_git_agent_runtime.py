from __future__ import annotations

import subprocess
from pathlib import Path

from hyperloop.reconciliation.adapters.git_agent_runtime import (
    GitAgentRuntime,
    _TASK_EPILOGUE,
    _VERIFICATION_EPILOGUE,
)
from hyperloop.reconciliation.models.agent_handle import AgentHandle
from hyperloop.reconciliation.models.agent_role import AgentRole
from hyperloop.reconciliation.models.agent_template import AgentTemplate
from hyperloop.reconciliation.models.event import Event, EventType
from hyperloop.reconciliation.models.event_reason import EventReason
from hyperloop.reconciliation.models.integration_summary import IntegrationSummary
from hyperloop.reconciliation.models.poll_result import (
    AgentStatus,
    AgentVerdict,
    PollResult,
)
from hyperloop.reconciliation.models.proposed_task import ProposedTask
from hyperloop.reconciliation.models.spec_diff import SpecDiff
from hyperloop.reconciliation.models.task import Task
from hyperloop.reconciliation.models.task_briefing import TaskBriefing

from tests.reconciliation.fakes.fake_agent_executor import FakeAgentExecutor
from tests.reconciliation.fakes.fake_prompt_composer import FakePromptComposer

_ALL_ROLE_TEMPLATES = [
    AgentTemplate(name=AgentRole.IMPLEMENTER, prompt="Implement.", guidelines=[]),
    AgentTemplate(name=AgentRole.VERIFIER, prompt="Verify.", guidelines=[]),
    AgentTemplate(name=AgentRole.DECOMPOSER, prompt="Decompose.", guidelines=[]),
    AgentTemplate(
        name=AgentRole.MERGE_RESOLVER, prompt="Resolve merge.", guidelines=[]
    ),
    AgentTemplate(
        name=AgentRole.INTEGRATION_SUMMARIZER, prompt="Summarize.", guidelines=[]
    ),
]


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
    composer: FakePromptComposer | None = None,
) -> GitAgentRuntime:
    return GitAgentRuntime(
        repo_path,
        branch_prefix=BRANCH_PREFIX,
        executor=executor or FakeAgentExecutor(),
        prompt_composer=composer or FakePromptComposer(_ALL_ROLE_TEMPLATES),
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


class TestDetectStale:
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
        stale = runtime.detect_stale()

        stale_ids = {h.id for h in stale}
        assert branch_5 in stale_ids
        assert branch_6 in stale_ids

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
        stale = runtime.detect_stale()

        stale_ids = {h.id for h in stale}
        assert branch_5 not in stale_ids
        assert branch_6 in stale_ids

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
        stale = runtime.detect_stale()

        stale_ids = {h.id for h in stale}
        assert branch_5 not in stale_ids
        assert branch_6 in stale_ids

    def test_finds_verifier_branches_without_signal(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        _create_branch_from(local, VERIFIER_BRANCH, "main")
        _create_work_commit(local, VERIFIER_BRANCH, "Checking specs")
        _push_branch(local, VERIFIER_BRANCH)

        runtime = _make_runtime(local)
        stale = runtime.detect_stale()

        stale_ids = {h.id for h in stale}
        assert VERIFIER_BRANCH in stale_ids

    def test_returns_empty_when_no_hyperloop_branches(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        runtime = _make_runtime(local)
        stale = runtime.detect_stale()
        assert stale == []

    def test_ignores_delivery_branches(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        delivery_branch = f"hyperloop/spec/{BLOB_SHA}"
        _create_branch_from(local, delivery_branch, "main")
        _push_branch(local, delivery_branch)

        runtime = _make_runtime(local)
        stale = runtime.detect_stale()

        stale_ids = {h.id for h in stale}
        assert delivery_branch not in stale_ids

    def test_ignores_plan_branch(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _create_branch_from(local, "hyperloop/plan", "main")
        _push_branch(local, "hyperloop/plan")

        runtime = _make_runtime(local)
        stale = runtime.detect_stale()
        assert stale == []

    def test_detects_stale_pushed_by_other_clone(
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
        stale = runtime.detect_stale()

        stale_ids = {h.id for h in stale}
        assert TASK_BRANCH in stale_ids


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

    def test_cancel_calls_executor_cancel_before_deleting_branch(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        _create_branch_from(local, TASK_BRANCH, "main")
        _push_branch(local, TASK_BRANCH)

        executor = FakeAgentExecutor()
        runtime = _make_runtime(local, executor=executor)
        handle = AgentHandle(id=TASK_BRANCH)
        runtime.cancel(handle)

        assert TASK_BRANCH in executor.cancelled_branches


class TestCustomBranchPrefix:
    def test_poll_works_with_custom_prefix(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        prefix = "myloop/"
        branch = f"{prefix}spec/abc123/task/1"

        _create_branch_from(local, branch, "main")
        _create_signal_commit(local, branch, "Done\n\nTask-Status: Complete")
        _push_branch(local, branch)

        runtime = GitAgentRuntime(
            local,
            branch_prefix=prefix,
            executor=FakeAgentExecutor(),
            prompt_composer=FakePromptComposer(_ALL_ROLE_TEMPLATES),
            remote="origin",
        )
        result = runtime.poll(AgentHandle(id=branch))

        assert result.status == AgentStatus.COMPLETE

    def test_detect_stale_uses_configured_prefix(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        prefix = "myloop/"
        branch = f"{prefix}spec/abc123/task/1"

        _create_branch_from(local, branch, "main")
        _create_work_commit(local, branch, "Work")
        _push_branch(local, branch)

        runtime = GitAgentRuntime(
            local,
            branch_prefix=prefix,
            executor=FakeAgentExecutor(),
            prompt_composer=FakePromptComposer(_ALL_ROLE_TEMPLATES),
            remote="origin",
        )
        stale = runtime.detect_stale()

        stale_ids = {h.id for h in stale}
        assert branch in stale_ids

    def test_detect_stale_ignores_other_prefixes(
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
            prompt_composer=FakePromptComposer(_ALL_ROLE_TEMPLATES),
            remote="origin",
        )
        stale = runtime.detect_stale()

        assert stale == []


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

    def test_passes_composed_prompt_to_executor(
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
        branch, prompt, _model = executor.started_tasks[0]
        assert branch == TASK_BRANCH
        assert isinstance(prompt, str)

    def test_composes_prompt_for_implementer_role(
        self,
        tmp_path: Path,
    ) -> None:
        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        executor = FakeAgentExecutor()
        runtime = _make_runtime(tmp_path, executor, composer)

        briefing = TaskBriefing(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            task_description="Implement auth endpoint",
            workspace_id=f"task/{BLOB_SHA}/5",
        )

        runtime.launch_task(briefing)

        assert len(composer.calls) == 1
        call = composer.calls[0]
        assert call.role == AgentRole.IMPLEMENTER
        assert call.substitutions["task_id"] == "5"
        assert call.substitutions["spec_ref"] == f"specs/auth.spec.md@{BLOB_SHA}"
        assert call.epilogue == _TASK_EPILOGUE

    def test_includes_spec_content_section(self, tmp_path: Path) -> None:
        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, composer=composer)

        briefing = TaskBriefing(
            spec_content="# Auth Spec\nRequirements here.",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            task_description="Implement auth",
            workspace_id=f"task/{BLOB_SHA}/5",
        )

        runtime.launch_task(briefing)

        call = composer.calls[0]
        spec_sections = [s for s in call.sections if s.heading == "Spec"]
        assert len(spec_sections) == 1
        assert "Auth Spec" in spec_sections[0].content

    def test_includes_events_section_when_retrying(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone

        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, composer=composer)

        now = datetime.now(timezone.utc)
        events = [
            Event(
                type=EventType.WARNING,
                reason=EventReason.TASK_FAILED,
                message="Tests did not pass",
                first_timestamp=now,
                last_timestamp=now,
            )
        ]
        briefing = TaskBriefing(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            task_description="Implement auth",
            events=events,
            workspace_id=f"task/{BLOB_SHA}/5",
        )

        runtime.launch_task(briefing)

        call = composer.calls[0]
        event_sections = [s for s in call.sections if s.heading == "Events"]
        assert len(event_sections) == 1
        assert "Tests did not pass" in event_sections[0].content

    def test_no_events_section_on_first_attempt(self, tmp_path: Path) -> None:
        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, composer=composer)

        briefing = TaskBriefing(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            task_description="Implement auth",
            workspace_id=f"task/{BLOB_SHA}/5",
        )

        runtime.launch_task(briefing)

        call = composer.calls[0]
        event_sections = [s for s in call.sections if s.heading == "Events"]
        assert len(event_sections) == 0

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
            local,
            branch_prefix=prefix,
            executor=executor,
            prompt_composer=FakePromptComposer(_ALL_ROLE_TEMPLATES),
            remote="origin",
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
                spec_content="# Auth Spec",
            ),
        ]
        result = runtime.launch_decomposition(spec_diffs, [], [])

        assert result == expected

    def test_passes_composed_prompt_to_executor(self, tmp_path: Path) -> None:
        executor = FakeAgentExecutor()
        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, executor, composer)

        spec_diffs = [
            SpecDiff(
                spec_path="specs/auth.spec.md",
                blob_sha=BLOB_SHA,
                diff_text="+ new requirement",
                spec_content="# Auth Spec",
            ),
        ]
        runtime.launch_decomposition(spec_diffs, [], [])

        assert len(executor.decomposition_calls) == 1
        prompt, _model = executor.decomposition_calls[0]
        assert isinstance(prompt, str)

    def test_composes_prompt_for_decomposer_role(self, tmp_path: Path) -> None:
        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, composer=composer)

        spec_diffs = [
            SpecDiff(
                spec_path="specs/auth.spec.md",
                blob_sha=BLOB_SHA,
                diff_text="+ new requirement",
                spec_content="# Auth Spec",
            ),
        ]
        runtime.launch_decomposition(spec_diffs, [], [])

        assert len(composer.calls) == 1
        assert composer.calls[0].role == AgentRole.DECOMPOSER

    def test_includes_spec_content_section(self, tmp_path: Path) -> None:
        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, composer=composer)

        spec_diffs = [
            SpecDiff(
                spec_path="specs/auth.spec.md",
                blob_sha=BLOB_SHA,
                diff_text="+ new requirement",
                spec_content="# Auth Spec\nFull content here.",
            ),
        ]
        runtime.launch_decomposition(spec_diffs, [], [])

        sections = composer.calls[0].sections
        content_sections = [s for s in sections if "Spec Content" in s.heading]
        assert len(content_sections) == 1
        assert "Full content here." in content_sections[0].content

    def test_includes_spec_diff_section_separate_from_content(
        self, tmp_path: Path
    ) -> None:
        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, composer=composer)

        spec_diffs = [
            SpecDiff(
                spec_path="specs/auth.spec.md",
                blob_sha=BLOB_SHA,
                diff_text="+ new requirement",
                spec_content="# Auth Spec\nFull content.",
            ),
        ]
        runtime.launch_decomposition(spec_diffs, [], [])

        sections = composer.calls[0].sections
        diff_sections = [s for s in sections if "Spec Diff" in s.heading]
        assert len(diff_sections) == 1
        assert "new requirement" in diff_sections[0].content

    def test_includes_spec_content_for_each_spec(self, tmp_path: Path) -> None:
        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, composer=composer)

        spec_diffs = [
            SpecDiff(
                spec_path="specs/auth.spec.md",
                blob_sha="sha1",
                diff_text="+ auth change",
                spec_content="# Auth Spec",
            ),
            SpecDiff(
                spec_path="specs/users.spec.md",
                blob_sha="sha2",
                diff_text="+ users change",
                spec_content="# Users Spec",
            ),
        ]
        runtime.launch_decomposition(spec_diffs, [], [])

        sections = composer.calls[0].sections
        content_sections = [s for s in sections if "Spec Content" in s.heading]
        assert len(content_sections) == 2

    def test_includes_spec_diffs_as_sections(self, tmp_path: Path) -> None:
        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, composer=composer)

        spec_diffs = [
            SpecDiff(
                spec_path="specs/auth.spec.md",
                blob_sha=BLOB_SHA,
                diff_text="+ new requirement",
                spec_content="# Auth Spec",
            ),
        ]
        runtime.launch_decomposition(spec_diffs, [], [])

        sections = composer.calls[0].sections
        assert any("auth.spec.md" in s.heading for s in sections)
        assert any("new requirement" in s.content for s in sections)

    def test_includes_existing_tasks_section(self, tmp_path: Path) -> None:
        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, composer=composer)

        tasks = [
            Task(
                id=1,
                spec_path="specs/auth.spec.md",
                spec_blob_sha=BLOB_SHA,
                name="implement-auth",
                description="Add auth endpoint",
            ),
        ]
        runtime.launch_decomposition([], tasks, [])

        sections = composer.calls[0].sections
        task_sections = [s for s in sections if s.heading == "Existing Tasks"]
        assert len(task_sections) == 1
        assert "implement-auth" in task_sections[0].content

    def test_includes_events_section(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone

        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, composer=composer)

        now = datetime.now(timezone.utc)
        events = [
            Event(
                type=EventType.WARNING,
                reason=EventReason.TASK_FAILED,
                message="Tests did not pass",
                first_timestamp=now,
                last_timestamp=now,
            )
        ]
        runtime.launch_decomposition([], [], events)

        sections = composer.calls[0].sections
        event_sections = [s for s in sections if s.heading == "Events"]
        assert len(event_sections) == 1
        assert "Tests did not pass" in event_sections[0].content

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
                spec_content="# Auth Spec",
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

    def test_passes_composed_prompt_to_executor(
        self, git_env: tuple[Path, Path]
    ) -> None:
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
        branch, prompt, _model = executor.started_verifications[0]
        assert branch == VERIFIER_BRANCH
        assert isinstance(prompt, str)

    def test_composes_prompt_for_verifier_role(self, tmp_path: Path) -> None:
        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, composer=composer)

        runtime.launch_verification(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            workspace_id=f"verification/{BLOB_SHA}",
        )

        assert len(composer.calls) == 1
        call = composer.calls[0]
        assert call.role == AgentRole.VERIFIER
        assert call.substitutions["spec_ref"] == f"specs/auth.spec.md@{BLOB_SHA}"
        assert call.epilogue == _VERIFICATION_EPILOGUE

    def test_includes_spec_content_section(self, tmp_path: Path) -> None:
        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, composer=composer)

        runtime.launch_verification(
            spec_content="# Auth Spec\nRequirements here.",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            workspace_id=f"verification/{BLOB_SHA}",
        )

        sections = composer.calls[0].sections
        spec_sections = [s for s in sections if s.heading == "Spec"]
        assert len(spec_sections) == 1
        assert "Auth Spec" in spec_sections[0].content

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
    def test_passes_composed_prompt_to_executor(self, tmp_path: Path) -> None:
        executor = FakeAgentExecutor()
        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, executor, composer)

        result = runtime.launch_merge_resolution(
            task_workspace_id=f"task/{BLOB_SHA}/5",
            delivery_workspace_id=f"delivery/{BLOB_SHA}",
            conflict_details="Conflict in auth.py",
        )

        assert result is True
        assert len(executor.merge_calls) == 1
        task_br, delivery_br, prompt, _model = executor.merge_calls[0]
        assert task_br == TASK_BRANCH
        assert delivery_br == f"{BRANCH_PREFIX}spec/{BLOB_SHA}/delivery"
        assert isinstance(prompt, str)

    def test_composes_prompt_for_merge_resolver_role(self, tmp_path: Path) -> None:
        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, composer=composer)

        runtime.launch_merge_resolution(
            task_workspace_id=f"task/{BLOB_SHA}/5",
            delivery_workspace_id=f"delivery/{BLOB_SHA}",
            conflict_details="Conflict in auth.py",
        )

        assert len(composer.calls) == 1
        call = composer.calls[0]
        assert call.role == AgentRole.MERGE_RESOLVER
        conflict_sections = [
            s for s in call.sections if s.heading == "Conflict Details"
        ]
        assert len(conflict_sections) == 1
        assert "Conflict in auth.py" in conflict_sections[0].content

    def test_returns_false_on_failure(self, tmp_path: Path) -> None:
        executor = FakeAgentExecutor()
        executor.set_merge_result(False)
        runtime = _make_runtime(tmp_path, executor)

        result = runtime.launch_merge_resolution(
            task_workspace_id=f"task/{BLOB_SHA}/5",
            delivery_workspace_id=f"delivery/{BLOB_SHA}",
            conflict_details="Conflict in auth.py",
        )

        assert result is False


class TestComposeIntegrationSummary:
    def test_passes_composed_prompt_to_executor(self, tmp_path: Path) -> None:
        expected = IntegrationSummary(title="Add auth", body="Implements auth spec")
        executor = FakeAgentExecutor()
        executor.set_integration_summary(expected)
        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, executor, composer)

        result = runtime.compose_integration_summary(
            spec_content="# Auth Spec",
            task_summaries=[("implement-auth", "Added auth endpoint")],
            verification_rationale="All requirements met",
        )

        assert result == expected
        assert len(executor.summary_calls) == 1
        prompt, _model = executor.summary_calls[0]
        assert isinstance(prompt, str)

    def test_composes_prompt_for_integration_summarizer_role(
        self, tmp_path: Path
    ) -> None:
        composer = FakePromptComposer(_ALL_ROLE_TEMPLATES)
        runtime = _make_runtime(tmp_path, composer=composer)

        runtime.compose_integration_summary(
            spec_content="# Auth Spec",
            task_summaries=[("implement-auth", "Added auth endpoint")],
            verification_rationale="All requirements met",
        )

        assert len(composer.calls) == 1
        call = composer.calls[0]
        assert call.role == AgentRole.INTEGRATION_SUMMARIZER
        headings = {s.heading for s in call.sections}
        assert "Spec" in headings
        assert "Completed Tasks" in headings
        assert "Verification Rationale" in headings

    def test_executor_failure_propagates(self, tmp_path: Path) -> None:
        executor = FakeAgentExecutor()
        executor.set_integration_summary_error(RuntimeError("LLM unavailable"))
        runtime = _make_runtime(tmp_path, executor)

        try:
            runtime.compose_integration_summary(
                spec_content="# Auth Spec",
                task_summaries=[],
                verification_rationale="All requirements met",
            )
            assert False, "Expected RuntimeError"
        except RuntimeError as exc:
            assert "LLM unavailable" in str(exc)


class TestModelSelection:
    def test_launch_task_passes_implementation_model_to_executor(
        self, tmp_path: Path
    ) -> None:
        executor = FakeAgentExecutor()
        runtime = GitAgentRuntime(
            tmp_path,
            branch_prefix=BRANCH_PREFIX,
            executor=executor,
            prompt_composer=FakePromptComposer(_ALL_ROLE_TEMPLATES),
            implementation_model="claude-sonnet",
        )
        briefing = TaskBriefing(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            task_description="Implement auth",
            workspace_id=f"task/{BLOB_SHA}/5",
        )

        runtime.launch_task(briefing)

        _, _, model = executor.started_tasks[0]
        assert model == "claude-sonnet"

    def test_launch_verification_passes_verification_model_to_executor(
        self, tmp_path: Path
    ) -> None:
        executor = FakeAgentExecutor()
        runtime = GitAgentRuntime(
            tmp_path,
            branch_prefix=BRANCH_PREFIX,
            executor=executor,
            prompt_composer=FakePromptComposer(_ALL_ROLE_TEMPLATES),
            verification_model="gemini-pro",
        )

        runtime.launch_verification(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            workspace_id=f"verification/{BLOB_SHA}",
        )

        _, _, model = executor.started_verifications[0]
        assert model == "gemini-pro"

    def test_launch_decomposition_passes_decomposition_model_to_executor(
        self, tmp_path: Path
    ) -> None:
        executor = FakeAgentExecutor()
        runtime = GitAgentRuntime(
            tmp_path,
            branch_prefix=BRANCH_PREFIX,
            executor=executor,
            prompt_composer=FakePromptComposer(_ALL_ROLE_TEMPLATES),
            decomposition_model="claude-opus",
        )

        spec_diffs = [
            SpecDiff(
                spec_path="specs/auth.spec.md",
                blob_sha=BLOB_SHA,
                diff_text="+ new requirement",
                spec_content="# Auth Spec",
            ),
        ]
        runtime.launch_decomposition(spec_diffs, [], [])

        _, model = executor.decomposition_calls[0]
        assert model == "claude-opus"

    def test_none_model_passes_none_to_executor(self, tmp_path: Path) -> None:
        executor = FakeAgentExecutor()
        runtime = _make_runtime(tmp_path, executor)
        briefing = TaskBriefing(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            task_description="Implement auth",
            workspace_id=f"task/{BLOB_SHA}/5",
        )

        runtime.launch_task(briefing)

        _, _, model = executor.started_tasks[0]
        assert model is None

    def test_different_models_for_implementation_and_verification(
        self, tmp_path: Path
    ) -> None:
        executor = FakeAgentExecutor()
        runtime = GitAgentRuntime(
            tmp_path,
            branch_prefix=BRANCH_PREFIX,
            executor=executor,
            prompt_composer=FakePromptComposer(_ALL_ROLE_TEMPLATES),
            implementation_model="claude-sonnet",
            verification_model="gemini-pro",
        )
        briefing = TaskBriefing(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            task_description="Implement auth",
            workspace_id=f"task/{BLOB_SHA}/5",
        )

        runtime.launch_task(briefing)
        runtime.launch_verification(
            spec_content="# Auth Spec",
            spec_path="specs/auth.spec.md",
            spec_blob_sha=BLOB_SHA,
            workspace_id=f"verification/{BLOB_SHA}",
        )

        _, _, task_model = executor.started_tasks[0]
        _, _, verify_model = executor.started_verifications[0]
        assert task_model == "claude-sonnet"
        assert verify_model == "gemini-pro"

    def test_merge_resolution_passes_none_model(self, tmp_path: Path) -> None:
        executor = FakeAgentExecutor()
        runtime = GitAgentRuntime(
            tmp_path,
            branch_prefix=BRANCH_PREFIX,
            executor=executor,
            prompt_composer=FakePromptComposer(_ALL_ROLE_TEMPLATES),
            implementation_model="claude-sonnet",
        )

        runtime.launch_merge_resolution(
            task_workspace_id=f"task/{BLOB_SHA}/5",
            delivery_workspace_id=f"delivery/{BLOB_SHA}",
            conflict_details="Conflict in auth.py",
        )

        _, _, _, model = executor.merge_calls[0]
        assert model is None

    def test_compose_summary_passes_none_model(self, tmp_path: Path) -> None:
        executor = FakeAgentExecutor()
        runtime = GitAgentRuntime(
            tmp_path,
            branch_prefix=BRANCH_PREFIX,
            executor=executor,
            prompt_composer=FakePromptComposer(_ALL_ROLE_TEMPLATES),
            implementation_model="claude-sonnet",
        )

        runtime.compose_integration_summary(
            spec_content="# Auth Spec",
            task_summaries=[("implement-auth", "Added auth endpoint")],
            verification_rationale="All requirements met",
        )

        _, model = executor.summary_calls[0]
        assert model is None


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

    def test_has_detect_stale_method(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitAgentRuntime.detect_stale)
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
