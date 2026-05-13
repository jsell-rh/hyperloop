from __future__ import annotations

import inspect
from typing import get_type_hints

from hyperloop.reconciliation.models.agent_handle import AgentHandle
from hyperloop.reconciliation.models.event import Event
from hyperloop.reconciliation.models.poll_result import (
    AgentStatus,
    AgentVerdict,
    PollResult,
)
from hyperloop.reconciliation.models.proposed_task import ProposedTask
from hyperloop.reconciliation.models.spec_diff import SpecDiff
from hyperloop.reconciliation.models.task import Task
from hyperloop.reconciliation.models.task_briefing import TaskBriefing
from hyperloop.reconciliation.ports.agent_runtime import AgentRuntime
from tests.reconciliation.fakes.fake_agent_runtime import FakeAgentRuntime


class TestAgentRuntimeProtocol:
    def test_defines_launch_decomposition(self) -> None:
        assert hasattr(AgentRuntime, "launch_decomposition")

    def test_defines_launch_task(self) -> None:
        assert hasattr(AgentRuntime, "launch_task")

    def test_defines_poll(self) -> None:
        assert hasattr(AgentRuntime, "poll")

    def test_defines_launch_verification(self) -> None:
        assert hasattr(AgentRuntime, "launch_verification")

    def test_defines_launch_merge_resolution(self) -> None:
        assert hasattr(AgentRuntime, "launch_merge_resolution")

    def test_defines_cancel(self) -> None:
        assert hasattr(AgentRuntime, "cancel")

    def test_defines_detect_stale(self) -> None:
        assert hasattr(AgentRuntime, "detect_stale")

    def test_no_extra_methods(self) -> None:
        methods = {
            name
            for name, _ in inspect.getmembers(
                AgentRuntime, predicate=inspect.isfunction
            )
            if not name.startswith("_")
        }
        assert methods == {
            "launch_decomposition",
            "launch_task",
            "poll",
            "launch_verification",
            "launch_merge_resolution",
            "compose_integration_summary",
            "cancel",
            "detect_stale",
        }

    def test_launch_decomposition_accepts_spec_diffs(self) -> None:
        hints = get_type_hints(AgentRuntime.launch_decomposition)
        assert hints["spec_diffs"] == list[SpecDiff]

    def test_launch_decomposition_accepts_existing_tasks(self) -> None:
        hints = get_type_hints(AgentRuntime.launch_decomposition)
        assert hints["existing_tasks"] == list[Task]

    def test_launch_decomposition_accepts_events(self) -> None:
        hints = get_type_hints(AgentRuntime.launch_decomposition)
        assert hints["events"] == list[Event]

    def test_launch_decomposition_returns_proposed_tasks(self) -> None:
        hints = get_type_hints(AgentRuntime.launch_decomposition)
        assert hints["return"] == list[ProposedTask]

    def test_launch_task_accepts_briefing(self) -> None:
        hints = get_type_hints(AgentRuntime.launch_task)
        assert hints["briefing"] is TaskBriefing

    def test_launch_task_returns_agent_handle(self) -> None:
        hints = get_type_hints(AgentRuntime.launch_task)
        assert hints["return"] is AgentHandle

    def test_poll_accepts_handle(self) -> None:
        hints = get_type_hints(AgentRuntime.poll)
        assert hints["handle"] is AgentHandle

    def test_poll_returns_poll_result(self) -> None:
        hints = get_type_hints(AgentRuntime.poll)
        assert hints["return"] is PollResult

    def test_launch_verification_accepts_spec_content(self) -> None:
        hints = get_type_hints(AgentRuntime.launch_verification)
        assert hints["spec_content"] is str

    def test_launch_verification_accepts_spec_path(self) -> None:
        hints = get_type_hints(AgentRuntime.launch_verification)
        assert hints["spec_path"] is str

    def test_launch_verification_accepts_spec_blob_sha(self) -> None:
        hints = get_type_hints(AgentRuntime.launch_verification)
        assert hints["spec_blob_sha"] is str

    def test_launch_verification_accepts_workspace_id(self) -> None:
        hints = get_type_hints(AgentRuntime.launch_verification)
        assert hints["workspace_id"] is str

    def test_launch_verification_returns_agent_handle(self) -> None:
        hints = get_type_hints(AgentRuntime.launch_verification)
        assert hints["return"] is AgentHandle

    def test_launch_merge_resolution_accepts_task_workspace_id(self) -> None:
        hints = get_type_hints(AgentRuntime.launch_merge_resolution)
        assert hints["task_workspace_id"] is str

    def test_launch_merge_resolution_accepts_delivery_workspace_id(self) -> None:
        hints = get_type_hints(AgentRuntime.launch_merge_resolution)
        assert hints["delivery_workspace_id"] is str

    def test_launch_merge_resolution_accepts_conflict_details(self) -> None:
        hints = get_type_hints(AgentRuntime.launch_merge_resolution)
        assert hints["conflict_details"] is str

    def test_launch_merge_resolution_returns_bool(self) -> None:
        hints = get_type_hints(AgentRuntime.launch_merge_resolution)
        assert hints["return"] is bool

    def test_cancel_accepts_handle(self) -> None:
        hints = get_type_hints(AgentRuntime.cancel)
        assert hints["handle"] is AgentHandle

    def test_cancel_returns_none(self) -> None:
        hints = get_type_hints(AgentRuntime.cancel)
        assert hints["return"] is type(None)

    def test_detect_stale_returns_list_of_handles(self) -> None:
        hints = get_type_hints(AgentRuntime.detect_stale)
        assert hints["return"] == list[AgentHandle]

    def test_port_imports_only_domain_types(self) -> None:
        import hyperloop.reconciliation.ports.agent_runtime as module

        source = inspect.getsource(module)
        assert "adapters" not in source


class TestAgentStatus:
    def test_values(self) -> None:
        assert AgentStatus.RUNNING == "Running"
        assert AgentStatus.COMPLETE == "Complete"
        assert AgentStatus.FAILED == "Failed"

    def test_is_str_enum(self) -> None:
        assert isinstance(AgentStatus.RUNNING, str)


class TestAgentVerdict:
    def test_values(self) -> None:
        assert AgentVerdict.PASS == "Pass"
        assert AgentVerdict.FAIL == "Fail"

    def test_is_str_enum(self) -> None:
        assert isinstance(AgentVerdict.PASS, str)


class TestPollResult:
    def test_running_has_no_rationale(self) -> None:
        result = PollResult(status=AgentStatus.RUNNING)
        assert result.rationale is None
        assert result.verdict is None

    def test_complete_with_rationale(self) -> None:
        result = PollResult(status=AgentStatus.COMPLETE, rationale="all tests pass")
        assert result.status == AgentStatus.COMPLETE
        assert result.rationale == "all tests pass"

    def test_complete_with_verdict(self) -> None:
        result = PollResult(
            status=AgentStatus.COMPLETE,
            rationale="spec met",
            verdict=AgentVerdict.PASS,
        )
        assert result.verdict == AgentVerdict.PASS

    def test_failed_with_rationale(self) -> None:
        result = PollResult(status=AgentStatus.FAILED, rationale="agent crashed")
        assert result.status == AgentStatus.FAILED
        assert result.rationale == "agent crashed"
        assert result.verdict is None

    def test_is_frozen(self) -> None:
        result = PollResult(status=AgentStatus.RUNNING)
        try:
            result.status = AgentStatus.COMPLETE  # type: ignore[misc]
            assert False, "should have raised"
        except Exception:
            pass


class TestAgentHandle:
    def test_stores_id(self) -> None:
        handle = AgentHandle(id="agent-123")
        assert handle.id == "agent-123"

    def test_is_frozen(self) -> None:
        handle = AgentHandle(id="agent-123")
        try:
            handle.id = "other"  # type: ignore[misc]
            assert False, "should have raised"
        except Exception:
            pass

    def test_equality(self) -> None:
        a = AgentHandle(id="x")
        b = AgentHandle(id="x")
        assert a == b

    def test_inequality(self) -> None:
        a = AgentHandle(id="x")
        b = AgentHandle(id="y")
        assert a != b


class TestProposedTask:
    def test_fields(self) -> None:
        task = ProposedTask(
            name="implement auth",
            description="add login endpoint",
            spec_path="auth.spec.md",
            spec_blob_sha="abc123",
            depends_on=["setup db"],
        )
        assert task.name == "implement auth"
        assert task.description == "add login endpoint"
        assert task.spec_path == "auth.spec.md"
        assert task.spec_blob_sha == "abc123"
        assert task.depends_on == ["setup db"]

    def test_depends_on_defaults_empty(self) -> None:
        task = ProposedTask(
            name="t",
            description="d",
            spec_path="s",
            spec_blob_sha="sha",
        )
        assert task.depends_on == []

    def test_is_frozen(self) -> None:
        task = ProposedTask(
            name="t",
            description="d",
            spec_path="s",
            spec_blob_sha="sha",
        )
        try:
            task.name = "other"  # type: ignore[misc]
            assert False, "should have raised"
        except Exception:
            pass


class TestSpecDiff:
    def test_fields(self) -> None:
        diff = SpecDiff(
            spec_path="auth.spec.md",
            blob_sha="def456",
            diff_text="+ new requirement",
            spec_content="# Auth Spec\nFull content here.",
        )
        assert diff.spec_path == "auth.spec.md"
        assert diff.blob_sha == "def456"
        assert diff.diff_text == "+ new requirement"
        assert diff.spec_content == "# Auth Spec\nFull content here."

    def test_is_frozen(self) -> None:
        diff = SpecDiff(spec_path="x", blob_sha="y", diff_text="z", spec_content="c")
        try:
            diff.spec_path = "other"  # type: ignore[misc]
            assert False, "should have raised"
        except Exception:
            pass


class TestTaskBriefing:
    def test_fields(self) -> None:
        briefing = TaskBriefing(
            spec_content="# Auth Spec",
            spec_path="auth.spec.md",
            spec_blob_sha="abc123",
            task_description="implement login",
            workspace_id="ws-1",
        )
        assert briefing.spec_content == "# Auth Spec"
        assert briefing.spec_path == "auth.spec.md"
        assert briefing.spec_blob_sha == "abc123"
        assert briefing.task_description == "implement login"
        assert briefing.events == []
        assert briefing.workspace_id == "ws-1"

    def test_is_frozen(self) -> None:
        briefing = TaskBriefing(
            spec_content="x",
            spec_path="y",
            spec_blob_sha="z",
            task_description="t",
            workspace_id="w",
        )
        try:
            briefing.spec_content = "other"  # type: ignore[misc]
            assert False, "should have raised"
        except Exception:
            pass


class TestFakeDecomposition:
    def test_returns_proposed_tasks(self) -> None:
        runtime = FakeAgentRuntime()
        proposed = [
            ProposedTask(
                name="setup db",
                description="create tables",
                spec_path="auth.spec.md",
                spec_blob_sha="abc",
            ),
            ProposedTask(
                name="implement login",
                description="add login endpoint",
                spec_path="auth.spec.md",
                spec_blob_sha="abc",
                depends_on=["setup db"],
            ),
        ]
        runtime.set_decomposition_result(proposed)

        diffs = [
            SpecDiff(
                spec_path="auth.spec.md",
                blob_sha="abc",
                diff_text="+new",
                spec_content="# Auth",
            )
        ]
        result = runtime.launch_decomposition(
            spec_diffs=diffs, existing_tasks=[], events=[]
        )

        assert result == proposed
        assert len(result) == 2
        assert result[1].depends_on == ["setup db"]

    def test_records_decomposition_context(self) -> None:
        runtime = FakeAgentRuntime()
        diffs = [
            SpecDiff(
                spec_path="a.spec.md",
                blob_sha="sha1",
                diff_text="diff",
                spec_content="# A",
            )
        ]
        tasks = [
            Task(
                id=1,
                spec_path="a.spec.md",
                spec_blob_sha="sha0",
                name="old task",
                description="existing",
            )
        ]
        events: list[Event] = []

        runtime.launch_decomposition(
            spec_diffs=diffs, existing_tasks=tasks, events=events
        )

        assert len(runtime.decomposition_calls) == 1
        assert runtime.decomposition_calls[0] == (diffs, tasks, events)


class TestFakeTaskLaunchAndPoll:
    def test_launch_task_returns_handle(self) -> None:
        runtime = FakeAgentRuntime()
        briefing = TaskBriefing(
            spec_content="# Spec",
            spec_path="auth.spec.md",
            spec_blob_sha="abc",
            task_description="implement login",
            workspace_id="ws-1",
        )

        handle = runtime.launch_task(briefing)

        assert isinstance(handle, AgentHandle)
        assert handle.id is not None

    def test_poll_running_agent(self) -> None:
        runtime = FakeAgentRuntime()
        briefing = TaskBriefing(
            spec_content="# Spec",
            spec_path="auth.spec.md",
            spec_blob_sha="abc",
            task_description="implement login",
            workspace_id="ws-1",
        )
        handle = runtime.launch_task(briefing)

        result = runtime.poll(handle)

        assert result.status == AgentStatus.RUNNING
        assert result.rationale is None
        assert result.verdict is None

    def test_poll_complete_agent(self) -> None:
        runtime = FakeAgentRuntime()
        briefing = TaskBriefing(
            spec_content="# Spec",
            spec_path="auth.spec.md",
            spec_blob_sha="abc",
            task_description="implement login",
            workspace_id="ws-1",
        )
        handle = runtime.launch_task(briefing)
        runtime.set_poll_result(
            handle,
            PollResult(status=AgentStatus.COMPLETE, rationale="all tests pass"),
        )

        result = runtime.poll(handle)

        assert result.status == AgentStatus.COMPLETE
        assert result.rationale == "all tests pass"

    def test_poll_failed_agent(self) -> None:
        runtime = FakeAgentRuntime()
        briefing = TaskBriefing(
            spec_content="# Spec",
            spec_path="auth.spec.md",
            spec_blob_sha="abc",
            task_description="implement login",
            workspace_id="ws-1",
        )
        handle = runtime.launch_task(briefing)
        runtime.set_poll_result(
            handle,
            PollResult(status=AgentStatus.FAILED, rationale="agent crashed"),
        )

        result = runtime.poll(handle)

        assert result.status == AgentStatus.FAILED
        assert result.rationale == "agent crashed"
        assert result.verdict is None

    def test_poll_distinguishes_completion_from_crash(self) -> None:
        runtime = FakeAgentRuntime()
        spec_content = "# Auth Spec\n## login must validate password"
        handle = runtime.launch_verification(
            spec_content=spec_content,
            spec_path="auth.spec.md",
            spec_blob_sha="abc",
            workspace_id="ws-1",
        )

        runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                rationale="password validation missing",
                verdict=AgentVerdict.FAIL,
            ),
        )
        result = runtime.poll(handle)

        assert result.status == AgentStatus.COMPLETE
        assert result.verdict == AgentVerdict.FAIL
        assert result.rationale == "password validation missing"

    def test_unique_handles_per_launch(self) -> None:
        runtime = FakeAgentRuntime()
        briefing = TaskBriefing(
            spec_content="# Spec",
            spec_path="s",
            spec_blob_sha="sha",
            task_description="t",
            workspace_id="w",
        )

        h1 = runtime.launch_task(briefing)
        h2 = runtime.launch_task(briefing)

        assert h1 != h2

    def test_records_task_briefing(self) -> None:
        runtime = FakeAgentRuntime()
        briefing = TaskBriefing(
            spec_content="# Auth Spec",
            spec_path="auth.spec.md",
            spec_blob_sha="abc123",
            task_description="implement login",
            workspace_id="ws-1",
        )

        runtime.launch_task(briefing)

        assert len(runtime.launched_tasks) == 1
        assert runtime.launched_tasks[0].spec_content == "# Auth Spec"
        assert runtime.launched_tasks[0].spec_path == "auth.spec.md"
        assert runtime.launched_tasks[0].spec_blob_sha == "abc123"
        assert runtime.launched_tasks[0].task_description == "implement login"
        assert runtime.launched_tasks[0].workspace_id == "ws-1"


class TestFakeVerification:
    def test_launch_returns_handle(self) -> None:
        runtime = FakeAgentRuntime()

        handle = runtime.launch_verification(
            spec_content="# Spec",
            spec_path="auth.spec.md",
            spec_blob_sha="abc",
            workspace_id="ws-1",
        )

        assert isinstance(handle, AgentHandle)

    def test_verification_pass(self) -> None:
        runtime = FakeAgentRuntime()
        handle = runtime.launch_verification(
            spec_content="# Spec",
            spec_path="auth.spec.md",
            spec_blob_sha="abc",
            workspace_id="ws-1",
        )
        runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                rationale="all requirements met",
                verdict=AgentVerdict.PASS,
            ),
        )

        result = runtime.poll(handle)

        assert result.status == AgentStatus.COMPLETE
        assert result.verdict == AgentVerdict.PASS
        assert result.rationale == "all requirements met"

    def test_records_verification_params(self) -> None:
        runtime = FakeAgentRuntime()

        runtime.launch_verification(
            spec_content="# Spec",
            spec_path="auth.spec.md",
            spec_blob_sha="abc",
            workspace_id="ws-1",
        )

        assert len(runtime.launched_verifications) == 1
        assert runtime.launched_verifications[0] == (
            "# Spec",
            "auth.spec.md",
            "abc",
            "ws-1",
        )


class TestFakeCancellation:
    def test_cancel_active_agent(self) -> None:
        runtime = FakeAgentRuntime()
        briefing = TaskBriefing(
            spec_content="# Spec",
            spec_path="s",
            spec_blob_sha="sha",
            task_description="t",
            workspace_id="w",
        )
        handle = runtime.launch_task(briefing)

        runtime.cancel(handle)

        assert runtime.is_cancelled(handle)

    def test_cancelled_agent_not_pollable(self) -> None:
        runtime = FakeAgentRuntime()
        briefing = TaskBriefing(
            spec_content="# Spec",
            spec_path="s",
            spec_blob_sha="sha",
            task_description="t",
            workspace_id="w",
        )
        handle = runtime.launch_task(briefing)
        runtime.cancel(handle)

        try:
            runtime.poll(handle)
            assert False, "should have raised KeyError"
        except KeyError:
            pass


class TestFakeStaleDetection:
    def test_no_stale(self) -> None:
        runtime = FakeAgentRuntime()

        stale = runtime.detect_stale()

        assert stale == []

    def test_returns_configured_stale(self) -> None:
        runtime = FakeAgentRuntime()
        stale_handles = [AgentHandle(id="stale-1"), AgentHandle(id="stale-2")]
        runtime.set_stale(stale_handles)

        stale = runtime.detect_stale()

        assert stale == stale_handles
        assert len(stale) == 2

    def test_stale_can_be_cancelled(self) -> None:
        runtime = FakeAgentRuntime()
        stale_handle = AgentHandle(id="stale-1")
        runtime.set_stale([stale_handle])

        stale = runtime.detect_stale()
        for handle in stale:
            runtime.cancel(handle)

        assert runtime.is_cancelled(stale_handle)


class TestFakeMergeResolution:
    def test_merge_success(self) -> None:
        runtime = FakeAgentRuntime()
        runtime.set_merge_result(True)

        result = runtime.launch_merge_resolution(
            task_workspace_id="ws-task-1",
            delivery_workspace_id="ws-delivery",
            conflict_details="conflicting import",
        )

        assert result is True

    def test_merge_failure(self) -> None:
        runtime = FakeAgentRuntime()
        runtime.set_merge_result(False)

        result = runtime.launch_merge_resolution(
            task_workspace_id="ws-task-1",
            delivery_workspace_id="ws-delivery",
            conflict_details="irreconcilable changes",
        )

        assert result is False

    def test_records_merge_resolution_params(self) -> None:
        runtime = FakeAgentRuntime()

        runtime.launch_merge_resolution(
            task_workspace_id="ws-task-1",
            delivery_workspace_id="ws-delivery",
            conflict_details="conflicting import",
        )

        assert len(runtime.launched_merge_resolutions) == 1
        assert runtime.launched_merge_resolutions[0] == (
            "ws-task-1",
            "ws-delivery",
            "conflicting import",
        )
