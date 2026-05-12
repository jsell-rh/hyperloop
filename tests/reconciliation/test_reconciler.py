from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hyperloop.reconciliation.models import SpecPlanStatus, Task, TaskStatus
from hyperloop.reconciliation.models.agent_handle import AgentHandle
from hyperloop.reconciliation.models.cancellation_reason import CancellationReason
from hyperloop.reconciliation.models.event import EventType
from hyperloop.reconciliation.models.event_reason import EventReason
from hyperloop.reconciliation.models.merge_result import MergeOutcome, MergeResult
from hyperloop.reconciliation.models.poll_result import (
    AgentStatus,
    AgentVerdict,
    PollResult,
)
from hyperloop.reconciliation.models.proposed_task import ProposedTask
from hyperloop.reconciliation.models.task_briefing import TaskBriefing
from hyperloop.reconciliation.models.spec_plan import SpecPlan
from hyperloop.reconciliation.ports.observer import ChangeType
from hyperloop.reconciliation.reconciler import Reconciler
from tests.reconciliation.fakes.fake_agent_runtime import FakeAgentRuntime
from tests.reconciliation.fakes.fake_observer import FakeObserver
from tests.reconciliation.fakes.fake_plan_store import FakePlanStore
from tests.reconciliation.fakes.fake_spec_source import FakeSpecSource
from tests.reconciliation.fakes.fake_workspace_manager import FakeWorkspaceManager


@pytest.fixture()
def spec_source() -> FakeSpecSource:
    return FakeSpecSource()


@pytest.fixture()
def plan_store() -> FakePlanStore:
    return FakePlanStore()


@pytest.fixture()
def observer() -> FakeObserver:
    return FakeObserver()


@pytest.fixture()
def agent_runtime() -> FakeAgentRuntime:
    return FakeAgentRuntime()


@pytest.fixture()
def workspace_manager() -> FakeWorkspaceManager:
    return FakeWorkspaceManager()


@pytest.fixture()
def reconciler(
    spec_source: FakeSpecSource,
    plan_store: FakePlanStore,
    observer: FakeObserver,
    agent_runtime: FakeAgentRuntime,
    workspace_manager: FakeWorkspaceManager,
) -> Reconciler:
    return Reconciler(
        spec_source=spec_source,
        plan_store=plan_store,
        observer=observer,
        agent_runtime=agent_runtime,
        workspace_manager=workspace_manager,
    )


class TestNoDrift:
    def test_empty_source_and_plan_does_nothing(
        self,
        reconciler: Reconciler,
        plan_store: FakePlanStore,
    ) -> None:
        reconciler.run_cycle()

        plan = plan_store.get_plan()
        assert plan.spec_plans == []

    def test_synced_spec_with_no_changes(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        plan_store.get_plan().add_spec("auth.spec.md", "abc123")

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        assert len(plan.spec_plans) == 1
        assert plan.spec_plans[0].blob_sha == "abc123"

    def test_no_divergence_events_when_synced(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        plan_store.get_plan().add_spec("auth.spec.md", "abc123")

        reconciler.run_cycle()

        assert observer.calls_for("spec_divergence_detected") == []


class TestNewSpecDetected:
    def test_new_spec_added_and_decomposed(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        spec_source.add_spec("users.spec.md", "abc123")
        agent_runtime.set_decomposition_result(
            [
                ProposedTask(
                    name="implement-users",
                    description="Implement users",
                    spec_path="users.spec.md",
                    spec_blob_sha="abc123",
                ),
            ]
        )

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        assert len(plan.spec_plans) == 1
        assert plan.spec_plans[0].path == "users.spec.md"
        assert plan.spec_plans[0].blob_sha == "abc123"
        assert plan.spec_plans[0].status == SpecPlanStatus.RECONCILING

    def test_new_spec_fires_divergence_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        observer: FakeObserver,
    ) -> None:
        spec_source.add_spec("users.spec.md", "abc123")

        reconciler.run_cycle()

        events = observer.calls_for("spec_divergence_detected")
        assert len(events) == 1
        assert events[0]["spec_path"] == "users.spec.md"
        assert events[0]["blob_sha"] == "abc123"
        assert events[0]["change_type"] == ChangeType.NEW

    def test_multiple_new_specs_all_detected(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "aaa111")
        spec_source.add_spec("users.spec.md", "bbb222")

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        assert len(plan.spec_plans) == 2
        paths = {sp.path for sp in plan.spec_plans}
        assert paths == {"auth.spec.md", "users.spec.md"}


class TestModifiedSpecDetected:
    def test_modified_spec_creates_new_plan_supersedes_old(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        plan_store.get_plan().add_spec("auth.spec.md", "abc123")
        spec_source.add_spec("auth.spec.md", "def456")
        agent_runtime.set_decomposition_result(
            [
                ProposedTask(
                    name="update-auth",
                    description="Update auth",
                    spec_path="auth.spec.md",
                    spec_blob_sha="def456",
                ),
            ]
        )

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        old = [sp for sp in plan.spec_plans if sp.blob_sha == "abc123"]
        new = [sp for sp in plan.spec_plans if sp.blob_sha == "def456"]
        assert len(old) == 1
        assert old[0].superseded is True
        assert len(new) == 1
        assert new[0].superseded is False
        assert new[0].status == SpecPlanStatus.RECONCILING

    def test_modified_spec_fires_divergence_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
    ) -> None:
        plan_store.get_plan().add_spec("auth.spec.md", "abc123")
        spec_source.add_spec("auth.spec.md", "def456")

        reconciler.run_cycle()

        events = observer.calls_for("spec_divergence_detected")
        assert len(events) == 1
        assert events[0]["spec_path"] == "auth.spec.md"
        assert events[0]["blob_sha"] == "def456"
        assert events[0]["change_type"] == ChangeType.MODIFIED

    def test_modified_spec_fires_superseded_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
    ) -> None:
        plan_store.get_plan().add_spec("auth.spec.md", "abc123")
        spec_source.add_spec("auth.spec.md", "def456")

        reconciler.run_cycle()

        events = observer.calls_for("spec_superseded")
        assert len(events) == 1
        assert events[0]["spec_path"] == "auth.spec.md"
        assert events[0]["old_sha"] == "abc123"
        assert events[0]["new_sha"] == "def456"


class TestDeletedSpecDetected:
    def test_deleted_spec_marked_superseded(
        self,
        reconciler: Reconciler,
        plan_store: FakePlanStore,
    ) -> None:
        plan_store.get_plan().add_spec("old-feature.spec.md", "abc123")

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        assert len(plan.spec_plans) == 1
        assert plan.spec_plans[0].superseded is True

    def test_deleted_spec_fires_divergence_event(
        self,
        reconciler: Reconciler,
        plan_store: FakePlanStore,
        observer: FakeObserver,
    ) -> None:
        plan_store.get_plan().add_spec("old-feature.spec.md", "abc123")

        reconciler.run_cycle()

        events = observer.calls_for("spec_divergence_detected")
        assert len(events) == 1
        assert events[0]["spec_path"] == "old-feature.spec.md"
        assert events[0]["change_type"] == ChangeType.DELETED

    def test_already_superseded_spec_not_re_detected(
        self,
        reconciler: Reconciler,
        plan_store: FakePlanStore,
        observer: FakeObserver,
    ) -> None:
        sp = plan_store.get_plan().add_spec("old.spec.md", "abc123")
        sp.superseded = True

        reconciler.run_cycle()

        assert observer.calls_for("spec_divergence_detected") == []


class TestIdempotentCycles:
    def test_running_twice_with_no_changes_is_idempotent(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")

        reconciler.run_cycle()
        plan_after_first = plan_store.get_plan().model_dump()

        reconciler.run_cycle()
        plan_after_second = plan_store.get_plan().model_dump()

        assert plan_after_first == plan_after_second

    def test_second_cycle_fires_no_divergence_events(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        observer: FakeObserver,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")

        reconciler.run_cycle()
        observer.calls.clear()

        reconciler.run_cycle()

        assert observer.calls_for("spec_divergence_detected") == []


class TestCycleLifecycle:
    def test_syncs_spec_source_each_cycle(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
    ) -> None:
        reconciler.run_cycle()
        reconciler.run_cycle()

        assert spec_source.sync_count == 2

    def test_persists_plan_each_cycle(
        self,
        reconciler: Reconciler,
        plan_store: FakePlanStore,
    ) -> None:
        reconciler.run_cycle()

        assert plan_store.write_count == 1

    def test_cycle_counter_increments(
        self,
        reconciler: Reconciler,
        observer: FakeObserver,
    ) -> None:
        reconciler.run_cycle()
        reconciler.run_cycle()

        cycle_starts = observer.calls_for("cycle_started")
        assert len(cycle_starts) == 2
        assert cycle_starts[0]["cycle"] == 1
        assert cycle_starts[1]["cycle"] == 2

    def test_cycle_completed_event_fires(
        self,
        reconciler: Reconciler,
        observer: FakeObserver,
    ) -> None:
        reconciler.run_cycle()

        completed = observer.calls_for("cycle_completed")
        assert len(completed) == 1
        assert completed[0]["cycle"] == 1

    def test_plan_synced_event_fires(
        self,
        reconciler: Reconciler,
        observer: FakeObserver,
    ) -> None:
        reconciler.run_cycle()

        synced = observer.calls_for("plan_synced")
        assert len(synced) == 1
        assert synced[0]["cycle"] == 1


def _build_in_progress_spec_plan(
    plan_store: FakePlanStore,
    workspace_manager: FakeWorkspaceManager,
    agent_runtime: FakeAgentRuntime | None = None,
    path: str = "auth.spec.md",
    blob_sha: str = "abc123",
) -> SpecPlan:
    plan = plan_store.get_plan()
    sp = plan.add_spec(path, blob_sha)
    sp.status = SpecPlanStatus.RECONCILING
    workspace_manager.create_delivery_workspace(blob_sha)

    handle_a = AgentHandle(id="agent-task-1")
    handle_b = AgentHandle(id="agent-task-2")
    id1 = plan.next_task_id()
    id2 = plan.next_task_id()
    ws1 = workspace_manager.create_task_workspace(blob_sha, id1, "D1")
    ws2 = workspace_manager.create_task_workspace(blob_sha, id2, "D2")
    plan.add_tasks(
        sp,
        [
            Task(
                id=id1,
                spec_path=path,
                spec_blob_sha=blob_sha,
                name="T1",
                description="D1",
                status=TaskStatus.IN_PROGRESS,
                agent_handle=handle_a,
                workspace_id=ws1,
            ),
            Task(
                id=id2,
                spec_path=path,
                spec_blob_sha=blob_sha,
                name="T2",
                description="D2",
                status=TaskStatus.IN_PROGRESS,
                agent_handle=handle_b,
                workspace_id=ws2,
            ),
        ],
    )

    if agent_runtime is not None:
        agent_runtime.set_poll_result(handle_a, PollResult(status=AgentStatus.RUNNING))
        agent_runtime.set_poll_result(handle_b, PollResult(status=AgentStatus.RUNNING))

    return sp


class TestSupersedingCancellation:
    def test_modified_spec_cancels_in_progress_task_agents(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        _build_in_progress_spec_plan(plan_store, workspace_manager)
        spec_source.add_spec("auth.spec.md", "def456")

        reconciler.run_cycle()

        assert agent_runtime.is_cancelled(AgentHandle(id="agent-task-1"))
        assert agent_runtime.is_cancelled(AgentHandle(id="agent-task-2"))

    def test_modified_spec_cleans_up_workspaces(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        _build_in_progress_spec_plan(plan_store, workspace_manager)
        spec_source.add_spec("auth.spec.md", "def456")

        reconciler.run_cycle()

        assert not workspace_manager.has_delivery_workspace("abc123")

    def test_modified_spec_fires_agent_cancelled_events(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        _build_in_progress_spec_plan(plan_store, workspace_manager)
        spec_source.add_spec("auth.spec.md", "def456")

        reconciler.run_cycle()

        cancelled = observer.calls_for("agent_cancelled")
        assert len(cancelled) == 2
        task_ids = {c["task_id"] for c in cancelled}
        assert task_ids == {1, 2}
        assert all(c["reason"] == CancellationReason.SUPERSEDED for c in cancelled)

    def test_deleted_spec_cancels_in_progress_task_agents(
        self,
        reconciler: Reconciler,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        _build_in_progress_spec_plan(plan_store, workspace_manager)

        reconciler.run_cycle()

        assert agent_runtime.is_cancelled(AgentHandle(id="agent-task-1"))
        assert agent_runtime.is_cancelled(AgentHandle(id="agent-task-2"))

    def test_deleted_spec_cleans_up_workspaces(
        self,
        reconciler: Reconciler,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        _build_in_progress_spec_plan(plan_store, workspace_manager)

        reconciler.run_cycle()

        assert not workspace_manager.has_delivery_workspace("abc123")

    def test_verification_cancelled_on_modified_spec(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        plan = plan_store.get_plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        sp.status = SpecPlanStatus.VERIFYING
        sp.verification_handle = AgentHandle(id="verifier-1")
        workspace_manager.create_delivery_workspace("abc123")
        spec_source.add_spec("auth.spec.md", "def456")

        reconciler.run_cycle()

        assert agent_runtime.is_cancelled(AgentHandle(id="verifier-1"))

    def test_verification_cancelled_on_deleted_spec(
        self,
        reconciler: Reconciler,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        plan = plan_store.get_plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        sp.status = SpecPlanStatus.VERIFYING
        sp.verification_handle = AgentHandle(id="verifier-1")
        workspace_manager.create_delivery_workspace("abc123")

        reconciler.run_cycle()

        assert agent_runtime.is_cancelled(AgentHandle(id="verifier-1"))

    def test_backlog_tasks_not_cancelled(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        plan = plan_store.get_plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        workspace_manager.create_delivery_workspace("abc123")
        plan.add_tasks(
            sp,
            [
                Task(
                    id=plan.next_task_id(),
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    name="T1",
                    description="D1",
                    status=TaskStatus.BACKLOG,
                ),
            ],
        )
        spec_source.add_spec("auth.spec.md", "def456")

        reconciler.run_cycle()

        assert observer.calls_for("agent_cancelled") == []

    def test_completed_tasks_not_cancelled(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        plan = plan_store.get_plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        workspace_manager.create_delivery_workspace("abc123")
        plan.add_tasks(
            sp,
            [
                Task(
                    id=plan.next_task_id(),
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    name="T1",
                    description="D1",
                    status=TaskStatus.COMPLETE,
                ),
            ],
        )
        spec_source.add_spec("auth.spec.md", "def456")

        reconciler.run_cycle()

        assert observer.calls_for("agent_cancelled") == []

    def test_no_cancellation_when_no_in_flight_work(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        plan_store.get_plan().add_spec("auth.spec.md", "abc123")
        spec_source.add_spec("auth.spec.md", "def456")

        reconciler.run_cycle()

        assert observer.calls_for("agent_cancelled") == []


class TestDecompositionDispatch:
    def test_out_of_sync_spec_decomposed_into_tasks(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_result(
            [
                ProposedTask(
                    name="implement-auth",
                    description="Implement authentication",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                ),
            ]
        )

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = next(sp for sp in plan.spec_plans if sp.path == "auth.spec.md")
        assert len(sp.tasks) == 1
        assert sp.tasks[0].name == "implement-auth"
        assert sp.tasks[0].description == "Implement authentication"
        assert sp.tasks[0].spec_path == "auth.spec.md"
        assert sp.tasks[0].spec_blob_sha == "abc123"
        assert sp.tasks[0].status == TaskStatus.IN_PROGRESS

    def test_spec_plan_transitions_to_reconciling(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_result(
            [
                ProposedTask(
                    name="implement-auth",
                    description="Implement auth",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                ),
            ]
        )

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = next(sp for sp in plan.spec_plans if sp.path == "auth.spec.md")
        assert sp.status == SpecPlanStatus.RECONCILING

    def test_tasks_assigned_monotonic_ids(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_result(
            [
                ProposedTask(
                    name="t1",
                    description="d1",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                ),
                ProposedTask(
                    name="t2",
                    description="d2",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                ),
                ProposedTask(
                    name="t3",
                    description="d3",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                ),
            ]
        )

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = next(sp for sp in plan.spec_plans if sp.path == "auth.spec.md")
        ids = [t.id for t in sp.tasks]
        assert ids == [1, 2, 3]

    def test_fresh_spec_diff_uses_none_as_old_sha(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        spec_source.set_diff("auth.spec.md", None, "abc123", "+new spec content")
        agent_runtime.set_decomposition_result([])

        reconciler.run_cycle()

        assert len(agent_runtime.decomposition_calls) == 1
        diffs, _, _ = agent_runtime.decomposition_calls[0]
        assert len(diffs) == 1
        assert diffs[0].spec_path == "auth.spec.md"
        assert diffs[0].blob_sha == "abc123"
        assert diffs[0].diff_text == "+new spec content"

    def test_modified_spec_uses_last_synced_sha_for_diff(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        plan = plan_store.get_plan()
        old_sp = plan.add_spec("auth.spec.md", "old_sha")
        old_sp.status = SpecPlanStatus.SYNCED

        spec_source.add_spec("auth.spec.md", "new_sha")
        spec_source.set_diff("auth.spec.md", "old_sha", "new_sha", "modified diff")
        agent_runtime.set_decomposition_result([])

        reconciler.run_cycle()

        assert len(agent_runtime.decomposition_calls) == 1
        diffs, _, _ = agent_runtime.decomposition_calls[0]
        assert diffs[0].diff_text == "modified diff"

    def test_prior_events_passed_to_decomposition(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        plan = plan_store.get_plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        sp.record_event(
            reason=EventReason.VERIFICATION_FAILED,
            message="timeout handling missing",
            event_type=EventType.WARNING,
            timestamp=datetime.now(timezone.utc),
        )
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_result([])

        reconciler.run_cycle()

        assert len(agent_runtime.decomposition_calls) == 1
        _, _, events = agent_runtime.decomposition_calls[0]
        assert len(events) == 1
        assert events[0].reason == EventReason.VERIFICATION_FAILED
        assert events[0].message == "timeout handling missing"

    def test_existing_tasks_passed_for_cross_spec_awareness(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        plan = plan_store.get_plan()
        other_sp = plan.add_spec("users.spec.md", "other_sha")
        other_sp.status = SpecPlanStatus.RECONCILING
        plan.add_tasks(
            other_sp,
            [
                Task(
                    id=plan.next_task_id(),
                    spec_path="users.spec.md",
                    spec_blob_sha="other_sha",
                    name="existing-task",
                    description="Already exists",
                ),
            ],
        )

        spec_source.add_spec("users.spec.md", "other_sha")
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_result([])

        reconciler.run_cycle()

        assert len(agent_runtime.decomposition_calls) == 1
        _, existing, _ = agent_runtime.decomposition_calls[0]
        assert len(existing) == 1
        assert existing[0].name == "existing-task"

    def test_dependency_resolution_by_name(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_result(
            [
                ProposedTask(
                    name="setup-db",
                    description="d1",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                ),
                ProposedTask(
                    name="implement-auth",
                    description="d2",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["setup-db"],
                ),
            ]
        )

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = next(sp for sp in plan.spec_plans if sp.path == "auth.spec.md")
        setup_task = next(t for t in sp.tasks if t.name == "setup-db")
        auth_task = next(t for t in sp.tasks if t.name == "implement-auth")
        assert auth_task.depends_on == [setup_task.id]

    def test_cross_spec_dependency_resolution(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        plan = plan_store.get_plan()
        other_sp = plan.add_spec("users.spec.md", "other_sha")
        other_sp.status = SpecPlanStatus.RECONCILING
        plan.add_tasks(
            other_sp,
            [
                Task(
                    id=plan.next_task_id(),
                    spec_path="users.spec.md",
                    spec_blob_sha="other_sha",
                    name="create-users-table",
                    description="Create users table",
                ),
            ],
        )

        spec_source.add_spec("users.spec.md", "other_sha")
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_result(
            [
                ProposedTask(
                    name="implement-auth",
                    description="d1",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["create-users-table"],
                ),
            ]
        )

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = next(
            sp
            for sp in plan.spec_plans
            if sp.path == "auth.spec.md" and not sp.superseded
        )
        auth_task = sp.tasks[0]
        assert auth_task.depends_on == [1]

    def test_zero_tasks_transitions_through_reconciling_to_verifying(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_result([])

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = next(sp for sp in plan.spec_plans if sp.path == "auth.spec.md")
        assert sp.status == SpecPlanStatus.VERIFYING

    def test_reconciling_spec_not_redecomposed(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        plan = plan_store.get_plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        sp.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("auth.spec.md", "abc123")

        reconciler.run_cycle()

        assert len(agent_runtime.decomposition_calls) == 0

    def test_no_decomposition_when_no_out_of_sync(
        self,
        reconciler: Reconciler,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        reconciler.run_cycle()

        assert len(agent_runtime.decomposition_calls) == 0
        assert observer.calls_for("decomposition_started") == []

    def test_multiple_specs_decomposed_with_correct_task_assignment(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "aaa")
        spec_source.add_spec("users.spec.md", "bbb")
        agent_runtime.set_decomposition_result(
            [
                ProposedTask(
                    name="t1",
                    description="d1",
                    spec_path="auth.spec.md",
                    spec_blob_sha="aaa",
                ),
                ProposedTask(
                    name="t2",
                    description="d2",
                    spec_path="users.spec.md",
                    spec_blob_sha="bbb",
                ),
            ]
        )

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        auth_sp = next(sp for sp in plan.spec_plans if sp.path == "auth.spec.md")
        users_sp = next(sp for sp in plan.spec_plans if sp.path == "users.spec.md")
        assert len(auth_sp.tasks) == 1
        assert auth_sp.tasks[0].name == "t1"
        assert len(users_sp.tasks) == 1
        assert users_sp.tasks[0].name == "t2"
        assert auth_sp.status == SpecPlanStatus.RECONCILING
        assert users_sp.status == SpecPlanStatus.RECONCILING

    def test_decomposition_started_event_fires(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_result([])

        reconciler.run_cycle()

        events = observer.calls_for("decomposition_started")
        assert len(events) == 1
        assert events[0]["specs_count"] == 1
        assert events[0]["cycle"] == 1

    def test_decomposition_completed_event_fires(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_result(
            [
                ProposedTask(
                    name="t1",
                    description="d1",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                ),
            ]
        )

        reconciler.run_cycle()

        events = observer.calls_for("decomposition_completed")
        assert len(events) == 1
        assert events[0]["specs_count"] == 1
        assert events[0]["tasks_created"] == 1
        assert events[0]["cycle"] == 1

    def test_task_created_events_fire(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_result(
            [
                ProposedTask(
                    name="t1",
                    description="d1",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                ),
                ProposedTask(
                    name="t2",
                    description="d2",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["t1"],
                ),
            ]
        )

        reconciler.run_cycle()

        events = observer.calls_for("task_created")
        assert len(events) == 2
        assert events[0]["name"] == "t1"
        assert events[0]["depends_on"] == []
        assert events[1]["name"] == "t2"
        assert events[1]["depends_on"] == [1]

    def test_task_ids_globally_unique_across_specs(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "aaa")
        spec_source.add_spec("users.spec.md", "bbb")
        agent_runtime.set_decomposition_result(
            [
                ProposedTask(
                    name="auth-t1",
                    description="d1",
                    spec_path="auth.spec.md",
                    spec_blob_sha="aaa",
                ),
                ProposedTask(
                    name="auth-t2",
                    description="d2",
                    spec_path="auth.spec.md",
                    spec_blob_sha="aaa",
                ),
                ProposedTask(
                    name="users-t1",
                    description="d3",
                    spec_path="users.spec.md",
                    spec_blob_sha="bbb",
                ),
            ]
        )

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        all_ids: list[int] = []
        for sp in plan.spec_plans:
            for t in sp.tasks:
                all_ids.append(t.id)
        assert all_ids == [1, 2, 3]
        assert len(set(all_ids)) == 3


def _build_reconciling_spec_plan(
    plan_store: FakePlanStore,
    spec_source: FakeSpecSource,
    path: str = "auth.spec.md",
    blob_sha: str = "abc123",
    spec_content: str = "# Auth Spec\nRequirements here",
    task_count: int = 2,
    task_status: TaskStatus = TaskStatus.BACKLOG,
) -> tuple[SpecPlan, list[Task]]:
    plan = plan_store.get_plan()
    sp = plan.add_spec(path, blob_sha)
    sp.status = SpecPlanStatus.RECONCILING
    spec_source.add_spec(path, blob_sha, content=spec_content)

    tasks: list[Task] = []
    for i in range(task_count):
        task_id = plan.next_task_id()
        tasks.append(
            Task(
                id=task_id,
                spec_path=path,
                spec_blob_sha=blob_sha,
                name=f"task-{task_id}",
                description=f"Task {task_id} description",
                status=task_status,
            )
        )
    plan.add_tasks(sp, tasks)
    return sp, tasks


class TestTaskDispatch:
    def test_unblocked_task_dispatched_to_in_progress(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
    ) -> None:
        _, tasks = _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)

        reconciler.run_cycle()

        assert tasks[0].status == TaskStatus.IN_PROGRESS

    def test_agent_handle_stored_on_dispatched_task(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
    ) -> None:
        _, tasks = _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)

        reconciler.run_cycle()

        assert tasks[0].agent_handle is not None

    def test_delivery_workspace_created(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)

        reconciler.run_cycle()

        assert workspace_manager.has_delivery_workspace("abc123")

    def test_task_workspace_created(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        _, tasks = _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)

        reconciler.run_cycle()

        assert workspace_manager.has_task_workspace("abc123", tasks[0].id)

    def test_agent_launched_with_correct_briefing(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        _build_reconciling_spec_plan(
            plan_store,
            spec_source,
            task_count=1,
            spec_content="# Auth\nMUST authenticate users",
        )

        reconciler.run_cycle()

        assert len(agent_runtime.launched_tasks) == 1
        briefing = agent_runtime.launched_tasks[0]
        assert briefing.spec_content == "# Auth\nMUST authenticate users"
        assert briefing.spec_path == "auth.spec.md"
        assert briefing.spec_blob_sha == "abc123"
        assert briefing.task_description == "Task 1 description"
        assert briefing.workspace_id == "task/abc123/1"

    def test_task_briefing_includes_events_on_retry(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        _, tasks = _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)
        tasks[0].record_event(
            reason=EventReason.TASK_FAILED,
            message="Test compilation error",
            event_type=EventType.WARNING,
            timestamp=datetime.now(timezone.utc),
        )

        reconciler.run_cycle()

        briefing = agent_runtime.launched_tasks[0]
        assert len(briefing.events) == 1
        assert briefing.events[0].reason == EventReason.TASK_FAILED
        assert briefing.events[0].message == "Test compilation error"

    def test_blocked_task_not_dispatched(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        plan = plan_store.get_plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        sp.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("auth.spec.md", "abc123")
        t1 = Task(
            id=plan.next_task_id(),
            spec_path="auth.spec.md",
            spec_blob_sha="abc123",
            name="t1",
            description="d1",
        )
        t2 = Task(
            id=plan.next_task_id(),
            spec_path="auth.spec.md",
            spec_blob_sha="abc123",
            name="t2",
            description="d2",
            depends_on=[t1.id],
        )
        plan.add_tasks(sp, [t1, t2])

        reconciler.run_cycle()

        assert t1.status == TaskStatus.IN_PROGRESS
        assert t2.status == TaskStatus.BACKLOG
        assert len(agent_runtime.launched_tasks) == 1

    def test_concurrent_limit_enforced(
        self,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        reconciler = Reconciler(
            spec_source=spec_source,
            plan_store=plan_store,
            observer=observer,
            agent_runtime=agent_runtime,
            workspace_manager=workspace_manager,
            max_concurrent_tasks=2,
        )
        _build_reconciling_spec_plan(plan_store, spec_source, task_count=4)

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = next(sp for sp in plan.spec_plans if sp.path == "auth.spec.md")
        in_progress = [t for t in sp.tasks if t.status == TaskStatus.IN_PROGRESS]
        backlog = [t for t in sp.tasks if t.status == TaskStatus.BACKLOG]
        assert len(in_progress) == 2
        assert len(backlog) == 2

    def test_concurrent_limit_accounts_for_already_in_progress(
        self,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        reconciler = Reconciler(
            spec_source=spec_source,
            plan_store=plan_store,
            observer=observer,
            agent_runtime=agent_runtime,
            workspace_manager=workspace_manager,
            max_concurrent_tasks=3,
        )
        plan = plan_store.get_plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        sp.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("auth.spec.md", "abc123")
        workspace_manager.create_delivery_workspace("abc123")
        existing_handle = AgentHandle(id="existing-agent")
        agent_runtime.set_poll_result(
            existing_handle, PollResult(status=AgentStatus.RUNNING)
        )
        plan.add_tasks(
            sp,
            [
                Task(
                    id=plan.next_task_id(),
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    name="running",
                    description="d0",
                    status=TaskStatus.IN_PROGRESS,
                    agent_handle=existing_handle,
                ),
                Task(
                    id=plan.next_task_id(),
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    name="backlog-1",
                    description="d1",
                ),
                Task(
                    id=plan.next_task_id(),
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    name="backlog-2",
                    description="d2",
                ),
                Task(
                    id=plan.next_task_id(),
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    name="backlog-3",
                    description="d3",
                ),
            ],
        )

        reconciler.run_cycle()

        in_progress = [t for t in sp.tasks if t.status == TaskStatus.IN_PROGRESS]
        backlog = [t for t in sp.tasks if t.status == TaskStatus.BACKLOG]
        assert len(in_progress) == 3
        assert len(backlog) == 1

    def test_already_in_progress_task_not_re_dispatched(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")

        reconciler.run_cycle()

        assert len(agent_runtime.launched_tasks) == 0

    def test_task_dispatched_observer_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
    ) -> None:
        _, tasks = _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)

        reconciler.run_cycle()

        events = observer.calls_for("task_dispatched")
        assert len(events) == 1
        assert events[0]["task_id"] == tasks[0].id
        assert events[0]["spec_path"] == "auth.spec.md"
        assert events[0]["spec_blob_sha"] == "abc123"
        assert events[0]["retry_count"] == 0
        assert events[0]["cycle"] == 1

    def test_multiple_tasks_dispatched_in_same_cycle(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        _build_reconciling_spec_plan(plan_store, spec_source, task_count=3)

        reconciler.run_cycle()

        assert len(agent_runtime.launched_tasks) == 3

    def test_each_task_gets_isolated_workspace(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        _build_reconciling_spec_plan(plan_store, spec_source, task_count=2)

        reconciler.run_cycle()

        workspace_ids = {b.workspace_id for b in agent_runtime.launched_tasks}
        assert len(workspace_ids) == 2

    def test_cycle_completed_reports_dispatched_count(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
    ) -> None:
        _build_reconciling_spec_plan(plan_store, spec_source, task_count=2)

        reconciler.run_cycle()

        completed = observer.calls_for("cycle_completed")
        assert completed[0]["tasks_dispatched"] == 2

    def test_launch_failure_skips_task_and_fires_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)
        original_launch = agent_runtime.launch_task

        def failing_launch(briefing: TaskBriefing) -> AgentHandle:
            raise RuntimeError("Agent unavailable")

        agent_runtime.launch_task = failing_launch  # type: ignore[assignment]

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = next(sp for sp in plan.spec_plans if sp.path == "auth.spec.md")
        assert sp.tasks[0].status == TaskStatus.BACKLOG
        events = observer.calls_for("agent_launch_failed")
        assert len(events) == 1
        assert events[0]["task_id"] == sp.tasks[0].id
        assert events[0]["role"] == "task"
        assert "Agent unavailable" in events[0]["reason"]

        agent_runtime.launch_task = original_launch  # type: ignore[assignment]


class TestResultCollection:
    def test_running_task_status_unchanged(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")

        reconciler.run_cycle()

        assert sp.tasks[0].status == TaskStatus.IN_PROGRESS
        assert sp.tasks[1].status == TaskStatus.IN_PROGRESS

    def test_complete_agent_marks_task_complete(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.COMPLETE),
        )

        reconciler.run_cycle()

        assert sp.tasks[0].status == TaskStatus.COMPLETE

    def test_complete_task_handle_cleared(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.COMPLETE),
        )

        reconciler.run_cycle()

        assert sp.tasks[0].agent_handle is None

    def test_failed_agent_resets_task_to_backlog_for_retry(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.FAILED, rationale="Compilation error"),
        )

        reconciler.run_cycle()

        assert sp.tasks[0].status == TaskStatus.BACKLOG
        assert sp.tasks[0].retry_count == 1

    def test_failed_task_records_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.FAILED, rationale="Compilation error"),
        )

        reconciler.run_cycle()

        assert len(sp.tasks[0].events) == 1
        assert sp.tasks[0].events[0].reason == EventReason.TASK_FAILED
        assert "Compilation error" in sp.tasks[0].events[0].message

    def test_task_completed_observer_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.COMPLETE),
        )

        reconciler.run_cycle()

        events = observer.calls_for("task_completed")
        assert len(events) == 1
        assert events[0]["task_id"] == sp.tasks[0].id
        assert events[0]["spec_path"] == "auth.spec.md"

    def test_task_failed_observer_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.FAILED, rationale="Compilation error"),
        )

        reconciler.run_cycle()

        events = observer.calls_for("task_failed")
        assert len(events) == 1
        assert events[0]["task_id"] == sp.tasks[0].id
        assert events[0]["reason"] == "Compilation error"

    def test_cycle_completed_reports_completion_counts(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.COMPLETE),
        )
        agent_runtime.set_poll_result(
            sp.tasks[1].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.FAILED, rationale="err"),
        )

        reconciler.run_cycle()

        completed = observer.calls_for("cycle_completed")
        assert completed[0]["tasks_completed"] == 1
        assert completed[0]["tasks_failed"] == 1


class TestMerge:
    def test_completed_task_merged_into_delivery_workspace(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.COMPLETE),
        )

        reconciler.run_cycle()

        events = observer.calls_for("task_merge_completed")
        assert len(events) == 1
        assert events[0]["task_id"] == sp.tasks[0].id
        assert events[0]["spec_blob_sha"] == "abc123"

    def test_successful_merge_cleans_up_task_workspace(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.COMPLETE),
        )

        reconciler.run_cycle()

        assert not workspace_manager.has_task_workspace("abc123", sp.tasks[0].id)

    def test_merge_conflict_launches_resolution_agent(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.COMPLETE),
        )
        workspace_manager.set_merge_result(
            "abc123",
            sp.tasks[0].id,
            MergeResult(
                outcome=MergeOutcome.CONFLICT,
                conflict_details="Both modified auth.py",
            ),
        )

        reconciler.run_cycle()

        events = observer.calls_for("merge_resolution_launched")
        assert len(events) == 1
        assert events[0]["task_id"] == sp.tasks[0].id

    def test_merge_resolution_success_completes_task(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.COMPLETE),
        )
        workspace_manager.set_merge_result(
            "abc123",
            sp.tasks[0].id,
            MergeResult(
                outcome=MergeOutcome.CONFLICT,
                conflict_details="Both modified auth.py",
            ),
        )
        agent_runtime.set_merge_result(True)

        reconciler.run_cycle()

        assert sp.tasks[0].status == TaskStatus.COMPLETE

    def test_merge_resolution_failure_resets_task_for_retry(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.COMPLETE),
        )
        workspace_manager.set_merge_result(
            "abc123",
            sp.tasks[0].id,
            MergeResult(
                outcome=MergeOutcome.CONFLICT,
                conflict_details="Both modified auth.py",
            ),
        )
        agent_runtime.set_merge_result(False)

        reconciler.run_cycle()

        assert sp.tasks[0].status == TaskStatus.BACKLOG
        assert sp.tasks[0].retry_count == 1


class TestTaskRetry:
    def test_retry_increments_retry_count(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.FAILED, rationale="Compilation error"),
        )

        reconciler.run_cycle()

        assert sp.tasks[0].retry_count == 1

    def test_retry_clears_agent_handle(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.FAILED, rationale="Compilation error"),
        )

        reconciler.run_cycle()

        assert sp.tasks[0].agent_handle is None

    def test_retry_fires_task_retried_observer_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.FAILED, rationale="Compilation error"),
        )

        reconciler.run_cycle()

        events = observer.calls_for("task_retried")
        assert len(events) == 1
        assert events[0]["task_id"] == sp.tasks[0].id
        assert events[0]["spec_path"] == "auth.spec.md"
        assert events[0]["reason"] == "Compilation error"
        assert events[0]["retry_count"] == 1
        assert events[0]["cycle"] == 1

    def test_retried_task_preserves_failure_events(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.FAILED, rationale="Compilation error"),
        )

        reconciler.run_cycle()

        assert len(sp.tasks[0].events) == 1
        assert sp.tasks[0].events[0].reason == EventReason.TASK_FAILED

    def test_retried_task_redispatched_next_cycle(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.FAILED, rationale="Compilation error"),
        )

        reconciler.run_cycle()
        assert sp.tasks[0].status == TaskStatus.BACKLOG
        assert sp.tasks[0].retry_count == 1

        reconciler.run_cycle()
        assert sp.tasks[0].status == TaskStatus.IN_PROGRESS
        assert sp.tasks[0].retry_count == 1

    def test_retried_task_briefing_includes_failure_events(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.FAILED, rationale="Compilation error"),
        )

        reconciler.run_cycle()
        agent_runtime.launched_tasks.clear()

        reconciler.run_cycle()

        assert len(agent_runtime.launched_tasks) >= 1
        briefing = next(
            b
            for b in agent_runtime.launched_tasks
            if b.task_description == sp.tasks[0].description
        )
        assert len(briefing.events) == 1
        assert briefing.events[0].reason == EventReason.TASK_FAILED
        assert briefing.events[0].message == "Compilation error"

    def test_retry_exhaustion_marks_task_failed(
        self,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        reconciler = Reconciler(
            spec_source=spec_source,
            plan_store=plan_store,
            observer=observer,
            agent_runtime=agent_runtime,
            workspace_manager=workspace_manager,
            max_task_retries=2,
        )
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        sp.tasks[0].retry_count = 2
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.FAILED, rationale="Still failing"),
        )

        reconciler.run_cycle()

        assert sp.tasks[0].status == TaskStatus.FAILED
        assert sp.tasks[0].retry_count == 2

    def test_retry_exhaustion_does_not_fire_task_retried(
        self,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        reconciler = Reconciler(
            spec_source=spec_source,
            plan_store=plan_store,
            observer=observer,
            agent_runtime=agent_runtime,
            workspace_manager=workspace_manager,
            max_task_retries=1,
        )
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        sp.tasks[0].retry_count = 1
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.FAILED, rationale="Still failing"),
        )

        reconciler.run_cycle()

        assert observer.calls_for("task_retried") == []

    def test_zero_max_retries_fails_immediately(
        self,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        reconciler = Reconciler(
            spec_source=spec_source,
            plan_store=plan_store,
            observer=observer,
            agent_runtime=agent_runtime,
            workspace_manager=workspace_manager,
            max_task_retries=0,
        )
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.FAILED, rationale="Failing"),
        )

        reconciler.run_cycle()

        assert sp.tasks[0].status == TaskStatus.FAILED
        assert sp.tasks[0].retry_count == 0
        assert observer.calls_for("task_retried") == []

    def test_task_failed_observer_fires_on_every_failure(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp = _build_in_progress_spec_plan(plan_store, workspace_manager, agent_runtime)
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.FAILED, rationale="Compilation error"),
        )

        reconciler.run_cycle()

        events = observer.calls_for("task_failed")
        assert len(events) == 1
        assert events[0]["task_id"] == sp.tasks[0].id
        assert events[0]["reason"] == "Compilation error"


def _build_all_tasks_complete_spec_plan(
    plan_store: FakePlanStore,
    spec_source: FakeSpecSource,
    workspace_manager: FakeWorkspaceManager,
    path: str = "auth.spec.md",
    blob_sha: str = "abc123",
    spec_content: str = "# Auth Spec\nRequirements here",
    task_count: int = 2,
) -> tuple[SpecPlan, list[Task]]:
    plan = plan_store.get_plan()
    sp = plan.add_spec(path, blob_sha)
    sp.status = SpecPlanStatus.RECONCILING
    spec_source.add_spec(path, blob_sha, content=spec_content)
    workspace_manager.create_delivery_workspace(blob_sha)
    sp.delivery_workspace_id = f"delivery/{blob_sha}"

    tasks: list[Task] = []
    for _ in range(task_count):
        task_id = plan.next_task_id()
        tasks.append(
            Task(
                id=task_id,
                spec_path=path,
                spec_blob_sha=blob_sha,
                name=f"task-{task_id}",
                description=f"Task {task_id} description",
                status=TaskStatus.COMPLETE,
                workspace_id=f"task/{blob_sha}/{task_id}",
            )
        )
    plan.add_tasks(sp, tasks)
    return sp, tasks


def _build_verifying_spec_plan(
    plan_store: FakePlanStore,
    spec_source: FakeSpecSource,
    workspace_manager: FakeWorkspaceManager,
    agent_runtime: FakeAgentRuntime,
    path: str = "auth.spec.md",
    blob_sha: str = "abc123",
    spec_content: str = "# Auth Spec\nRequirements here",
    task_count: int = 2,
    reconciliation_attempts: int = 0,
) -> tuple[SpecPlan, AgentHandle]:
    plan = plan_store.get_plan()
    sp = plan.add_spec(path, blob_sha)
    sp.reconciliation_attempts = reconciliation_attempts
    spec_source.add_spec(path, blob_sha, content=spec_content)
    workspace_manager.create_delivery_workspace(blob_sha)
    sp.delivery_workspace_id = f"delivery/{blob_sha}"

    tasks: list[Task] = []
    for _ in range(task_count):
        task_id = plan.next_task_id()
        tasks.append(
            Task(
                id=task_id,
                spec_path=path,
                spec_blob_sha=blob_sha,
                name=f"task-{task_id}",
                description=f"Task {task_id} description",
                status=TaskStatus.COMPLETE,
                workspace_id=f"task/{blob_sha}/{task_id}",
            )
        )
    plan.add_tasks(sp, tasks)
    sp.status = SpecPlanStatus.VERIFYING

    verification_handle = AgentHandle(id="verifier-1")
    sp.verification_handle = verification_handle
    agent_runtime.set_poll_result(
        verification_handle, PollResult(status=AgentStatus.RUNNING)
    )

    return sp, verification_handle


class TestVerificationLaunch:
    def test_all_tasks_complete_launches_verification(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        _build_all_tasks_complete_spec_plan(plan_store, spec_source, workspace_manager)

        reconciler.run_cycle()

        assert len(agent_runtime.launched_verifications) == 1

    def test_verification_workspace_created(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        _build_all_tasks_complete_spec_plan(plan_store, spec_source, workspace_manager)

        reconciler.run_cycle()

        assert workspace_manager.has_verification_workspace("abc123")

    def test_verification_agent_launched_with_correct_params(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        _build_all_tasks_complete_spec_plan(
            plan_store,
            spec_source,
            workspace_manager,
            spec_content="# Auth\nMUST verify users",
        )

        reconciler.run_cycle()

        spec_content, spec_path, blob_sha, workspace_id = (
            agent_runtime.launched_verifications[0]
        )
        assert spec_content == "# Auth\nMUST verify users"
        assert spec_path == "auth.spec.md"
        assert blob_sha == "abc123"
        assert workspace_id == "verification/abc123"

    def test_spec_transitions_to_verifying(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp, _ = _build_all_tasks_complete_spec_plan(
            plan_store, spec_source, workspace_manager
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.VERIFYING

    def test_verification_handle_stored(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp, _ = _build_all_tasks_complete_spec_plan(
            plan_store, spec_source, workspace_manager
        )

        reconciler.run_cycle()

        assert sp.verification_handle is not None

    def test_verification_launched_observer_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        _build_all_tasks_complete_spec_plan(plan_store, spec_source, workspace_manager)

        reconciler.run_cycle()

        events = observer.calls_for("verification_launched")
        assert len(events) == 1
        assert events[0]["spec_path"] == "auth.spec.md"
        assert events[0]["spec_blob_sha"] == "abc123"
        assert events[0]["cycle"] == 1

    def test_zero_tasks_triggers_verification(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        _build_all_tasks_complete_spec_plan(
            plan_store, spec_source, workspace_manager, task_count=0
        )

        reconciler.run_cycle()

        assert len(agent_runtime.launched_verifications) == 1

    def test_incomplete_tasks_no_verification(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        plan = plan_store.get_plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        sp.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("auth.spec.md", "abc123")
        workspace_manager.create_delivery_workspace("abc123")
        sp.delivery_workspace_id = "delivery/abc123"
        plan.add_tasks(
            sp,
            [
                Task(
                    id=plan.next_task_id(),
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    name="t1",
                    description="d1",
                    status=TaskStatus.COMPLETE,
                ),
                Task(
                    id=plan.next_task_id(),
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    name="t2",
                    description="d2",
                    status=TaskStatus.IN_PROGRESS,
                    agent_handle=AgentHandle(id="agent-t2"),
                ),
            ],
        )
        agent_runtime.set_poll_result(
            AgentHandle(id="agent-t2"), PollResult(status=AgentStatus.RUNNING)
        )

        reconciler.run_cycle()

        assert len(agent_runtime.launched_verifications) == 0

    def test_verifying_spec_not_relaunched(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )

        reconciler.run_cycle()

        assert len(agent_runtime.launched_verifications) == 0

    def test_synced_spec_not_re_verified(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        plan = plan_store.get_plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        sp.status = SpecPlanStatus.SYNCED
        spec_source.add_spec("auth.spec.md", "abc123")

        reconciler.run_cycle()

        assert len(agent_runtime.launched_verifications) == 0

    def test_launch_failure_fires_event_and_continues(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        _build_all_tasks_complete_spec_plan(plan_store, spec_source, workspace_manager)
        original_launch = agent_runtime.launch_verification

        def failing_launch(
            spec_content: str, spec_path: str, spec_blob_sha: str, workspace_id: str
        ) -> AgentHandle:
            raise RuntimeError("Verification agent unavailable")

        agent_runtime.launch_verification = failing_launch  # type: ignore[assignment]

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = next(sp for sp in plan.spec_plans if sp.path == "auth.spec.md")
        assert sp.status == SpecPlanStatus.RECONCILING
        events = observer.calls_for("verification_launch_failed")
        assert len(events) == 1
        assert events[0]["spec_path"] == "auth.spec.md"
        assert events[0]["spec_blob_sha"] == "abc123"
        assert "Verification agent unavailable" in events[0]["reason"]

        agent_runtime.launch_verification = original_launch  # type: ignore[assignment]


class TestVerificationPass:
    def test_verification_pass_transitions_to_synced(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="All checks pass",
            ),
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.SYNCED

    def test_verification_passed_event_recorded(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="All checks pass",
            ),
        )

        reconciler.run_cycle()

        passed_events = [
            e for e in sp.events if e.reason == EventReason.VERIFICATION_PASSED
        ]
        assert len(passed_events) == 1

    def test_verification_pass_integrates_to_trunk(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="Pass",
            ),
        )

        reconciler.run_cycle()

        assert len(workspace_manager.integrations) == 1
        assert workspace_manager.integrations[0] == ("abc123", "auth.spec.md")

    def test_trunk_integration_started_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="Pass",
            ),
        )

        reconciler.run_cycle()

        events = observer.calls_for("trunk_integration_started")
        assert len(events) == 1
        assert events[0]["spec_path"] == "auth.spec.md"
        assert events[0]["spec_blob_sha"] == "abc123"

    def test_trunk_integration_completed_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="Pass",
            ),
        )

        reconciler.run_cycle()

        events = observer.calls_for("trunk_integration_completed")
        assert len(events) == 1

    def test_verification_passed_observer_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="All checks pass",
            ),
        )

        reconciler.run_cycle()

        events = observer.calls_for("verification_passed")
        assert len(events) == 1
        assert events[0]["spec_path"] == "auth.spec.md"
        assert events[0]["spec_blob_sha"] == "abc123"
        assert events[0]["rationale"] == "All checks pass"
        assert events[0]["cycle"] == 1

    def test_spec_synced_observer_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="Pass",
            ),
        )

        reconciler.run_cycle()

        events = observer.calls_for("spec_synced")
        assert len(events) == 1
        assert events[0]["spec_path"] == "auth.spec.md"
        assert events[0]["spec_blob_sha"] == "abc123"
        assert events[0]["total_tasks"] == 2
        assert events[0]["cycle"] == 1

    def test_verification_handle_cleared_on_pass(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="Pass",
            ),
        )

        reconciler.run_cycle()

        assert sp.verification_handle is None


class TestVerificationFail:
    def test_verification_fail_transitions_to_out_of_sync(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.FAIL,
                rationale="Missing timeout handling",
            ),
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.OUT_OF_SYNC

    def test_verification_failed_event_recorded_with_rationale(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.FAIL,
                rationale="Missing timeout handling",
            ),
        )

        reconciler.run_cycle()

        failed_events = [
            e for e in sp.events if e.reason == EventReason.VERIFICATION_FAILED
        ]
        assert len(failed_events) == 1
        assert "Missing timeout handling" in failed_events[0].message

    def test_verification_failed_observer_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.FAIL,
                rationale="Missing timeout handling",
            ),
        )

        reconciler.run_cycle()

        events = observer.calls_for("verification_failed")
        assert len(events) == 1
        assert events[0]["spec_path"] == "auth.spec.md"
        assert events[0]["spec_blob_sha"] == "abc123"
        assert events[0]["rationale"] == "Missing timeout handling"
        assert events[0]["cycle"] == 1

    def test_reconciliation_attempts_incremented(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store,
            spec_source,
            workspace_manager,
            agent_runtime,
            reconciliation_attempts=0,
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.FAIL,
                rationale="Fail",
            ),
        )

        reconciler.run_cycle()

        assert sp.reconciliation_attempts == 1

    def test_verification_handle_cleared_on_fail(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.FAIL,
                rationale="Fail",
            ),
        )

        reconciler.run_cycle()

        assert sp.verification_handle is None

    def test_verification_workspace_cleaned_up_on_fail(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        workspace_manager._verification_workspaces.add("abc123")
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.FAIL,
                rationale="Fail",
            ),
        )

        reconciler.run_cycle()

        assert not workspace_manager.has_verification_workspace("abc123")

    def test_redecomposition_count_reset_on_fail(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        sp.redecomposition_count = 1
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.FAIL,
                rationale="Fail",
            ),
        )

        reconciler.run_cycle()

        assert sp.redecomposition_count == 0

    def test_poll_exception_leaves_spec_verifying(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        original_poll = agent_runtime.poll

        def failing_poll(h: AgentHandle) -> PollResult:
            raise RuntimeError("Connection refused")

        agent_runtime.poll = failing_poll  # type: ignore[assignment]

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.VERIFYING
        assert sp.verification_handle is not None

        agent_runtime.poll = original_poll  # type: ignore[assignment]

    def test_verdict_none_treated_as_failure(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=None,
                rationale="Agent returned no verdict",
            ),
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.OUT_OF_SYNC
        assert sp.verification_handle is None


class TestConvergenceBound:
    def test_verification_fail_at_convergence_bound_transitions_to_failed(
        self,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        reconciler = Reconciler(
            spec_source=spec_source,
            plan_store=plan_store,
            observer=observer,
            agent_runtime=agent_runtime,
            workspace_manager=workspace_manager,
            convergence_bound=3,
        )
        sp, handle = _build_verifying_spec_plan(
            plan_store,
            spec_source,
            workspace_manager,
            agent_runtime,
            reconciliation_attempts=2,
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.FAIL,
                rationale="Still failing",
            ),
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.FAILED

    def test_spec_failed_observer_event(
        self,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        reconciler = Reconciler(
            spec_source=spec_source,
            plan_store=plan_store,
            observer=observer,
            agent_runtime=agent_runtime,
            workspace_manager=workspace_manager,
            convergence_bound=3,
        )
        sp, handle = _build_verifying_spec_plan(
            plan_store,
            spec_source,
            workspace_manager,
            agent_runtime,
            reconciliation_attempts=2,
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.FAIL,
                rationale="Still failing",
            ),
        )

        reconciler.run_cycle()

        events = observer.calls_for("spec_failed")
        assert len(events) == 1
        assert events[0]["spec_path"] == "auth.spec.md"
        assert events[0]["spec_blob_sha"] == "abc123"

    def test_under_convergence_bound_transitions_to_out_of_sync(
        self,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        reconciler = Reconciler(
            spec_source=spec_source,
            plan_store=plan_store,
            observer=observer,
            agent_runtime=agent_runtime,
            workspace_manager=workspace_manager,
            convergence_bound=3,
        )
        sp, handle = _build_verifying_spec_plan(
            plan_store,
            spec_source,
            workspace_manager,
            agent_runtime,
            reconciliation_attempts=1,
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.FAIL,
                rationale="Fail",
            ),
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.OUT_OF_SYNC


class TestIntegrationFailure:
    def test_integration_failure_fires_trunk_integration_failed_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="Pass",
            ),
        )
        workspace_manager._delivery_workspaces.discard("abc123")

        reconciler.run_cycle()

        events = observer.calls_for("trunk_integration_failed")
        assert len(events) == 1
        assert events[0]["spec_path"] == "auth.spec.md"

    def test_integration_failure_keeps_spec_retryable(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="Pass",
            ),
        )
        workspace_manager._delivery_workspaces.discard("abc123")

        reconciler.run_cycle()

        assert sp.status != SpecPlanStatus.SYNCED
        assert sp.status == SpecPlanStatus.VERIFYING

    def test_integration_failure_clears_verification_handle(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="Pass",
            ),
        )
        workspace_manager._delivery_workspaces.discard("abc123")

        reconciler.run_cycle()

        assert sp.verification_handle is None

    def test_integration_retried_on_next_cycle(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="Pass",
            ),
        )
        workspace_manager._delivery_workspaces.discard("abc123")

        reconciler.run_cycle()

        workspace_manager._delivery_workspaces.add("abc123")

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.SYNCED

    def test_integration_failure_increments_attempts(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="Pass",
            ),
        )
        workspace_manager._delivery_workspaces.discard("abc123")

        reconciler.run_cycle()

        assert sp.integration_attempts == 1

    def test_integration_failure_records_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="Pass",
            ),
        )
        workspace_manager._delivery_workspaces.discard("abc123")

        reconciler.run_cycle()

        failed_events = [
            e for e in sp.events if e.reason == EventReason.INTEGRATION_FAILED
        ]
        assert len(failed_events) == 1

    def test_integration_retry_limit_transitions_to_failed(
        self,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        reconciler = Reconciler(
            spec_source=spec_source,
            plan_store=plan_store,
            observer=observer,
            agent_runtime=agent_runtime,
            workspace_manager=workspace_manager,
            max_integration_retries=2,
        )
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="Pass",
            ),
        )
        workspace_manager._delivery_workspaces.discard("abc123")

        reconciler.run_cycle()
        assert sp.status == SpecPlanStatus.VERIFYING
        assert sp.integration_attempts == 1

        reconciler.run_cycle()
        assert sp.status == SpecPlanStatus.FAILED
        assert sp.integration_attempts == 2

    def test_integration_retry_limit_fires_spec_failed_event(
        self,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        reconciler = Reconciler(
            spec_source=spec_source,
            plan_store=plan_store,
            observer=observer,
            agent_runtime=agent_runtime,
            workspace_manager=workspace_manager,
            max_integration_retries=1,
        )
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="Pass",
            ),
        )
        workspace_manager._delivery_workspaces.discard("abc123")

        reconciler.run_cycle()

        events = observer.calls_for("spec_failed")
        assert len(events) == 1
        assert events[0]["spec_path"] == "auth.spec.md"

    def test_successful_integration_resets_attempts(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp, handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="Pass",
            ),
        )

        reconciler.run_cycle()

        assert sp.integration_attempts == 0
