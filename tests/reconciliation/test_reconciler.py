from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hyperloop.reconciliation.models import SpecPlanStatus, Task, TaskStatus
from hyperloop.reconciliation.models.agent_handle import AgentHandle
from hyperloop.reconciliation.models.cancellation_reason import CancellationReason
from hyperloop.reconciliation.models.event import EventType
from hyperloop.reconciliation.models.event_reason import EventReason
from hyperloop.reconciliation.models.integration_poll_result import (
    IntegrationPollResult,
    IntegrationPollStatus,
)
from hyperloop.reconciliation.models.integration_summary import IntegrationSummary
from hyperloop.reconciliation.models.merge_result import MergeOutcome, MergeResult
from hyperloop.reconciliation.models.rebase_context import RebaseContext
from hyperloop.reconciliation.models.rebase_result import RebaseOutcome, RebaseResult
from hyperloop.reconciliation.models.poll_result import (
    AgentStatus,
    AgentVerdict,
    PollResult,
)
from hyperloop.reconciliation.models.proposed_task import ProposedTask
from hyperloop.reconciliation.models.spec_plan import SpecPlan
from hyperloop.reconciliation.ports.observer import ChangeType
from hyperloop.reconciliation.reconciler import Reconciler
from tests.reconciliation.fakes.fake_agent_runtime import FakeAgentRuntime
from tests.reconciliation.fakes.fake_observer import FakeObserver
from tests.reconciliation.fakes.fake_plan_store import FakePlanStore
from tests.reconciliation.fakes.fake_prompt_composer import FakePromptComposer
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

    def test_fresh_spec_has_none_old_blob_sha(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_result([])

        reconciler.run_cycle()

        assert len(agent_runtime.decomposition_calls) == 1
        diffs, _, _ = agent_runtime.decomposition_calls[0]
        assert len(diffs) == 1
        assert diffs[0].spec_path == "auth.spec.md"
        assert diffs[0].blob_sha == "abc123"
        assert diffs[0].old_blob_sha is None

    def test_decomposition_receives_blob_sha_for_each_spec(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "sha1")
        spec_source.add_spec("users.spec.md", "sha2")
        agent_runtime.set_decomposition_result([])

        reconciler.run_cycle()

        diffs, _, _ = agent_runtime.decomposition_calls[0]
        refs_by_path = {d.spec_path: d.blob_sha for d in diffs}
        assert refs_by_path["auth.spec.md"] == "sha1"
        assert refs_by_path["users.spec.md"] == "sha2"

    def test_modified_spec_passes_old_blob_sha(
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
        agent_runtime.set_decomposition_result([])

        reconciler.run_cycle()

        assert len(agent_runtime.decomposition_calls) == 1
        diffs, _, _ = agent_runtime.decomposition_calls[0]
        assert diffs[0].blob_sha == "new_sha"
        assert diffs[0].old_blob_sha == "old_sha"

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

    def test_workspace_briefing_contains_task_details(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        _, tasks = _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)

        reconciler.run_cycle()

        briefing = workspace_manager.get_task_briefing("abc123", tasks[0].id)
        assert f"Task {tasks[0].id}" in briefing
        assert tasks[0].name in briefing
        assert tasks[0].description in briefing

    def test_workspace_briefing_contains_spec_reference(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        _, tasks = _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)

        reconciler.run_cycle()

        briefing = workspace_manager.get_task_briefing("abc123", tasks[0].id)
        assert "auth.spec.md" in briefing
        assert "abc123" in briefing

    def test_workspace_briefing_contains_events_on_retry(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        _, tasks = _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)
        tasks[0].record_event(
            reason=EventReason.TASK_FAILED,
            message="Test compilation error",
            event_type=EventType.WARNING,
            timestamp=datetime.now(timezone.utc),
        )

        reconciler.run_cycle()

        briefing = workspace_manager.get_task_briefing("abc123", tasks[0].id)
        assert "TaskFailed" in briefing
        assert "Test compilation error" in briefing

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

    def test_launch_failure_fires_agent_launch_failed_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)
        agent_runtime.set_launch_task_error(RuntimeError("Agent unavailable"))

        reconciler.run_cycle()

        events = observer.calls_for("agent_launch_failed")
        assert len(events) == 1
        assert events[0]["role"] == "task"
        assert "Agent unavailable" in events[0]["reason"]


class TestLaunchFailure:
    def test_launch_failure_marks_task_for_retry(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        _, tasks = _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)
        agent_runtime.set_launch_task_error(RuntimeError("worktree add failed"))

        reconciler.run_cycle()

        assert tasks[0].status == TaskStatus.BACKLOG
        assert tasks[0].retry_count == 1

    def test_launch_failure_increments_retry_count(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        _, tasks = _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)
        agent_runtime.set_launch_task_error(RuntimeError("worktree add failed"))

        reconciler.run_cycle()
        reconciler.run_cycle()

        assert tasks[0].retry_count == 2

    def test_launch_failure_fires_task_failed_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        _, tasks = _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)
        agent_runtime.set_launch_task_error(RuntimeError("worktree add failed"))

        reconciler.run_cycle()

        events = observer.calls_for("task_failed")
        assert len(events) == 1
        assert events[0]["task_id"] == tasks[0].id
        assert "worktree add failed" in events[0]["reason"]

    def test_launch_failure_clears_workspace_id(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        _, tasks = _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)
        agent_runtime.set_launch_task_error(RuntimeError("worktree add failed"))

        reconciler.run_cycle()

        assert tasks[0].workspace_id is None

    def test_launch_failure_exhausts_retries(
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
        _, tasks = _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)
        agent_runtime.set_launch_task_error(RuntimeError("worktree add failed"))

        for _ in range(3):
            reconciler.run_cycle()

        assert tasks[0].status == TaskStatus.FAILED
        assert tasks[0].retry_count == 2

    def test_launch_failure_does_not_set_agent_handle(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        _, tasks = _build_reconciling_spec_plan(plan_store, spec_source, task_count=1)
        agent_runtime.set_launch_task_error(RuntimeError("worktree add failed"))

        reconciler.run_cycle()

        assert tasks[0].agent_handle is None


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


_DEAD_AGENT_RATIONALE = "Agent died without producing a signal commit"


class TestDeadAgentHandling:
    def test_dead_task_agent_resets_to_backlog_for_retry(
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
            PollResult(status=AgentStatus.FAILED, rationale=_DEAD_AGENT_RATIONALE),
        )

        reconciler.run_cycle()

        assert sp.tasks[0].status == TaskStatus.BACKLOG
        assert sp.tasks[0].retry_count == 1

    def test_dead_task_agent_records_failure_event_with_rationale(
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
            PollResult(status=AgentStatus.FAILED, rationale=_DEAD_AGENT_RATIONALE),
        )

        reconciler.run_cycle()

        failed_events = [
            e for e in sp.tasks[0].events if e.reason == EventReason.TASK_FAILED
        ]
        assert len(failed_events) == 1
        assert _DEAD_AGENT_RATIONALE in failed_events[0].message

    def test_dead_task_agent_clears_handle(
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
            PollResult(status=AgentStatus.FAILED, rationale=_DEAD_AGENT_RATIONALE),
        )

        reconciler.run_cycle()

        assert sp.tasks[0].agent_handle is None

    def test_dead_task_agent_fires_observer_events(
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
            PollResult(status=AgentStatus.FAILED, rationale=_DEAD_AGENT_RATIONALE),
        )

        reconciler.run_cycle()

        failed_events = observer.calls_for("task_failed")
        assert len(failed_events) == 1
        assert failed_events[0]["task_id"] == sp.tasks[0].id
        assert failed_events[0]["reason"] == _DEAD_AGENT_RATIONALE

        retried_events = observer.calls_for("task_retried")
        assert len(retried_events) == 1
        assert retried_events[0]["task_id"] == sp.tasks[0].id

    def test_dead_task_agent_at_retry_limit_marks_failed(
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
            PollResult(status=AgentStatus.FAILED, rationale=_DEAD_AGENT_RATIONALE),
        )

        reconciler.run_cycle()

        assert sp.tasks[0].status == TaskStatus.FAILED

    def test_dead_task_agent_retry_exhaustion_triggers_redecomposition(
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
            max_redecompositions=1,
        )
        sp, _ = _build_retry_exhausted_spec_plan(
            plan_store, spec_source, agent_runtime, workspace_manager
        )
        agent_runtime.set_poll_result(
            sp.tasks[0].agent_handle,  # type: ignore[arg-type]
            PollResult(status=AgentStatus.FAILED, rationale=_DEAD_AGENT_RATIONALE),
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.OUT_OF_SYNC
        assert sp.redecomposition_count == 1

    def test_dead_verification_agent_transitions_spec_to_out_of_sync(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp, verification_handle = _build_verifying_spec_plan(
            plan_store, spec_source, workspace_manager, agent_runtime
        )
        agent_runtime.set_poll_result(
            verification_handle,
            PollResult(status=AgentStatus.FAILED, rationale=_DEAD_AGENT_RATIONALE),
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.OUT_OF_SYNC
        assert sp.verification_handle is None
        failed_events = observer.calls_for("verification_failed")
        assert len(failed_events) == 1
        assert failed_events[0]["rationale"] == _DEAD_AGENT_RATIONALE


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

        spec_content, spec_path, blob_sha, workspace_id, _rebase_ctx = (
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

    def test_workspace_creation_failure_fires_event_and_continues(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        _build_all_tasks_complete_spec_plan(plan_store, spec_source, workspace_manager)
        original_create = workspace_manager.create_verification_workspace

        def failing_create(blob_sha: str) -> str:
            raise RuntimeError("Branch already exists")

        workspace_manager.create_verification_workspace = failing_create  # type: ignore[assignment]

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = next(sp for sp in plan.spec_plans if sp.path == "auth.spec.md")
        assert sp.status == SpecPlanStatus.RECONCILING
        events = observer.calls_for("verification_launch_failed")
        assert len(events) == 1
        assert events[0]["spec_path"] == "auth.spec.md"
        assert "Branch already exists" in events[0]["reason"]

        workspace_manager.create_verification_workspace = original_create  # type: ignore[assignment]


class TestVerificationPass:
    def test_verification_pass_transitions_to_pending_integration(
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

        assert sp.status == SpecPlanStatus.PENDING_INTEGRATION
        assert sp.integration_id is not None

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
        blob_sha, spec_path, _title, _body = workspace_manager.integrations[0]
        assert blob_sha == "abc123"
        assert spec_path == "auth.spec.md"

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
        assert sp.status == SpecPlanStatus.PENDING_INTEGRATION

        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.MERGED),
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

        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.MERGED),
        )
        reconciler.run_cycle()

        events = observer.calls_for("spec_synced")
        assert len(events) == 1
        assert events[0]["spec_path"] == "auth.spec.md"
        assert events[0]["spec_blob_sha"] == "abc123"
        assert events[0]["total_tasks"] == 2
        assert events[0]["cycle"] == 2

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

    def test_verification_workspace_cleaned_up_on_pass(
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
                verdict=AgentVerdict.PASS,
                rationale="All checks pass",
            ),
        )

        reconciler.run_cycle()

        assert not workspace_manager.has_verification_workspace("abc123")


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

        assert sp.status == SpecPlanStatus.PENDING_INTEGRATION

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


def _build_retry_exhausted_spec_plan(
    plan_store: FakePlanStore,
    spec_source: FakeSpecSource,
    agent_runtime: FakeAgentRuntime,
    workspace_manager: FakeWorkspaceManager,
    path: str = "auth.spec.md",
    blob_sha: str = "abc123",
    max_task_retries: int = 2,
) -> tuple[SpecPlan, list[Task]]:
    plan = plan_store.get_plan()
    sp = plan.add_spec(path, blob_sha)
    sp.status = SpecPlanStatus.RECONCILING
    spec_source.add_spec(path, blob_sha)
    workspace_manager.create_delivery_workspace(blob_sha)
    sp.delivery_workspace_id = f"delivery/{blob_sha}"

    handle_a = AgentHandle(id="agent-task-1")
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
                retry_count=max_task_retries,
            ),
            Task(
                id=id2,
                spec_path=path,
                spec_blob_sha=blob_sha,
                name="T2",
                description="D2",
                status=TaskStatus.COMPLETE,
                workspace_id=ws2,
            ),
        ],
    )
    agent_runtime.set_poll_result(
        handle_a,
        PollResult(status=AgentStatus.FAILED, rationale="Still failing"),
    )
    return sp, sp.tasks


class TestRedecomposition:
    def test_retry_exhaustion_triggers_redecomposition(
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
            max_redecompositions=1,
        )
        sp, _ = _build_retry_exhausted_spec_plan(
            plan_store, spec_source, agent_runtime, workspace_manager
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.OUT_OF_SYNC
        assert sp.redecomposition_count == 1

    def test_redecomposition_fires_observer_event(
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
            max_redecompositions=1,
        )
        _build_retry_exhausted_spec_plan(
            plan_store, spec_source, agent_runtime, workspace_manager
        )

        reconciler.run_cycle()

        events = observer.calls_for("redecomposition_triggered")
        assert len(events) == 1
        assert events[0]["spec_path"] == "auth.spec.md"
        assert events[0]["spec_blob_sha"] == "abc123"
        assert events[0]["failed_task_count"] == 1
        assert events[0]["cycle"] == 1

    def test_redecomposition_cancels_in_progress_tasks(
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
            max_redecompositions=1,
        )
        plan = plan_store.get_plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        sp.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("auth.spec.md", "abc123")
        workspace_manager.create_delivery_workspace("abc123")
        sp.delivery_workspace_id = "delivery/abc123"

        handle_a = AgentHandle(id="agent-a")
        handle_b = AgentHandle(id="agent-b")
        id1 = plan.next_task_id()
        id2 = plan.next_task_id()
        plan.add_tasks(
            sp,
            [
                Task(
                    id=id1,
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    name="T1",
                    description="D1",
                    status=TaskStatus.IN_PROGRESS,
                    agent_handle=handle_a,
                    retry_count=2,
                ),
                Task(
                    id=id2,
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    name="T2",
                    description="D2",
                    status=TaskStatus.IN_PROGRESS,
                    agent_handle=handle_b,
                ),
            ],
        )
        agent_runtime.set_poll_result(
            handle_a, PollResult(status=AgentStatus.FAILED, rationale="Error")
        )
        agent_runtime.set_poll_result(handle_b, PollResult(status=AgentStatus.RUNNING))

        reconciler.run_cycle()

        assert agent_runtime.is_cancelled(handle_b)
        cancelled = observer.calls_for("agent_cancelled")
        cancelled_ids = {c["task_id"] for c in cancelled}
        assert id2 in cancelled_ids

    def test_redecomposition_budget_exhausted_fails_spec(
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
            max_redecompositions=1,
        )
        sp, _ = _build_retry_exhausted_spec_plan(
            plan_store, spec_source, agent_runtime, workspace_manager
        )
        sp.redecomposition_count = 1

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.FAILED

    def test_redecomposition_budget_exhausted_fires_spec_failed(
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
            max_redecompositions=1,
        )
        sp, _ = _build_retry_exhausted_spec_plan(
            plan_store, spec_source, agent_runtime, workspace_manager
        )
        sp.redecomposition_count = 1

        reconciler.run_cycle()

        events = observer.calls_for("spec_failed")
        assert len(events) == 1
        assert events[0]["spec_path"] == "auth.spec.md"
        assert events[0]["spec_blob_sha"] == "abc123"

    def test_redecomposed_spec_picked_up_in_next_cycle(
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
            max_redecompositions=1,
        )
        sp, _ = _build_retry_exhausted_spec_plan(
            plan_store, spec_source, agent_runtime, workspace_manager
        )
        agent_runtime.set_decomposition_result(
            [
                ProposedTask(
                    name="new-approach",
                    description="Different approach",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                ),
            ]
        )

        reconciler.run_cycle()
        assert sp.status == SpecPlanStatus.OUT_OF_SYNC

        reconciler.run_cycle()

        assert len(agent_runtime.decomposition_calls) == 1
        _, _, events = agent_runtime.decomposition_calls[0]
        task_failed_events = [e for e in events if e.reason == EventReason.TASK_FAILED]
        assert len(task_failed_events) >= 1

    def test_no_redecomposition_when_no_failed_tasks(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        plan = plan_store.get_plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        sp.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("auth.spec.md", "abc123")
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

        reconciler.run_cycle()

        assert observer.calls_for("redecomposition_triggered") == []
        assert observer.calls_for("spec_failed") == []


def _build_cross_spec_scenario(
    plan_store: FakePlanStore,
    spec_source: FakeSpecSource,
    workspace_manager: FakeWorkspaceManager,
) -> tuple[SpecPlan, SpecPlan, Task, Task]:
    plan = plan_store.get_plan()

    sp_y = plan.add_spec("spec-y.spec.md", "sha-y1")
    sp_y.status = SpecPlanStatus.RECONCILING
    spec_source.add_spec("spec-y.spec.md", "sha-y1")
    workspace_manager.create_delivery_workspace("sha-y1")
    task_a = Task(
        id=plan.next_task_id(),
        spec_path="spec-y.spec.md",
        spec_blob_sha="sha-y1",
        name="task-A",
        description="Task A in spec Y",
        status=TaskStatus.BACKLOG,
    )
    plan.add_tasks(sp_y, [task_a])

    sp_x = plan.add_spec("spec-x.spec.md", "sha-x1")
    sp_x.status = SpecPlanStatus.RECONCILING
    spec_source.add_spec("spec-x.spec.md", "sha-x1")
    workspace_manager.create_delivery_workspace("sha-x1")
    task_b = Task(
        id=plan.next_task_id(),
        spec_path="spec-x.spec.md",
        spec_blob_sha="sha-x1",
        name="task-B",
        description="Task B in spec X",
        status=TaskStatus.BACKLOG,
        depends_on=[task_a.id],
    )
    plan.add_tasks(sp_x, [task_b])

    return sp_y, sp_x, task_a, task_b


class TestCrossSpecDependencyInvalidation:
    def test_superseding_invalidates_cross_spec_dependency(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp_y, sp_x, task_a, task_b = _build_cross_spec_scenario(
            plan_store, spec_source, workspace_manager
        )
        spec_source.add_spec("spec-y.spec.md", "sha-y2")

        reconciler.run_cycle()

        assert task_b.status == TaskStatus.FAILED
        dep_events = observer.calls_for("dependency_invalidated")
        assert len(dep_events) == 1
        assert dep_events[0]["task_id"] == task_b.id
        assert dep_events[0]["spec_path"] == "spec-x.spec.md"
        assert dep_events[0]["dependency_task_id"] == task_a.id

    def test_deleted_spec_invalidates_cross_spec_dependency(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp_y, sp_x, task_a, task_b = _build_cross_spec_scenario(
            plan_store, spec_source, workspace_manager
        )
        spec_source.remove_spec("spec-y.spec.md")

        reconciler.run_cycle()

        assert task_b.status == TaskStatus.FAILED
        dep_events = observer.calls_for("dependency_invalidated")
        assert len(dep_events) == 1
        assert dep_events[0]["task_id"] == task_b.id

    def test_dependency_invalidated_records_event_on_task(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp_y, sp_x, task_a, task_b = _build_cross_spec_scenario(
            plan_store, spec_source, workspace_manager
        )
        spec_source.add_spec("spec-y.spec.md", "sha-y2")

        reconciler.run_cycle()

        dep_events = [
            e for e in task_b.events if e.reason == EventReason.DEPENDENCY_INVALIDATED
        ]
        assert len(dep_events) == 1

    def test_no_retries_for_dependency_invalidated(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp_y, sp_x, task_a, task_b = _build_cross_spec_scenario(
            plan_store, spec_source, workspace_manager
        )
        spec_source.add_spec("spec-y.spec.md", "sha-y2")

        reconciler.run_cycle()

        assert task_b.status == TaskStatus.FAILED
        assert task_b.retry_count == 0
        assert observer.calls_for("task_retried") == []

    def test_dependency_invalidated_counts_toward_redecomposition(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp_y, sp_x, task_a, task_b = _build_cross_spec_scenario(
            plan_store, spec_source, workspace_manager
        )
        spec_source.add_spec("spec-y.spec.md", "sha-y2")

        reconciler.run_cycle()

        redecomp = observer.calls_for("redecomposition_triggered")
        assert len(redecomp) == 1
        assert redecomp[0]["spec_path"] == "spec-x.spec.md"

    def test_failed_spec_dependency_stays_blocked(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp_y, sp_x, task_a, task_b = _build_cross_spec_scenario(
            plan_store, spec_source, workspace_manager
        )
        sp_y.status = SpecPlanStatus.FAILED

        reconciler.run_cycle()

        assert task_b.status == TaskStatus.BACKLOG
        assert observer.calls_for("dependency_invalidated") == []

    def test_unresolvable_dependency_at_dispatch(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        plan = plan_store.get_plan()
        sp = plan.add_spec("spec-x.spec.md", "sha-x1")
        sp.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-x.spec.md", "sha-x1")
        workspace_manager.create_delivery_workspace("sha-x1")
        task_c = Task(
            id=plan.next_task_id(),
            spec_path="spec-x.spec.md",
            spec_blob_sha="sha-x1",
            name="task-C",
            description="Task C with phantom dependency",
            status=TaskStatus.BACKLOG,
            depends_on=[99],
        )
        plan.add_tasks(sp, [task_c])

        reconciler.run_cycle()

        assert task_c.status == TaskStatus.FAILED
        dep_events = observer.calls_for("dependency_invalidated")
        assert len(dep_events) == 1
        assert dep_events[0]["task_id"] == task_c.id
        assert dep_events[0]["dependency_task_id"] == 99
        redecomp = observer.calls_for("redecomposition_triggered")
        assert len(redecomp) == 1
        assert redecomp[0]["spec_path"] == "spec-x.spec.md"

    def test_same_spec_dependencies_not_affected_by_other_supersede(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        plan = plan_store.get_plan()

        sp_y = plan.add_spec("spec-y.spec.md", "sha-y1")
        sp_y.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-y.spec.md", "sha-y1")
        workspace_manager.create_delivery_workspace("sha-y1")
        task_a = Task(
            id=plan.next_task_id(),
            spec_path="spec-y.spec.md",
            spec_blob_sha="sha-y1",
            name="task-A",
            description="Task A",
            status=TaskStatus.COMPLETE,
        )
        plan.add_tasks(sp_y, [task_a])

        sp_z = plan.add_spec("spec-z.spec.md", "sha-z1")
        sp_z.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-z.spec.md", "sha-z1")
        workspace_manager.create_delivery_workspace("sha-z1")

        sp_x = plan.add_spec("spec-x.spec.md", "sha-x1")
        sp_x.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-x.spec.md", "sha-x1")
        workspace_manager.create_delivery_workspace("sha-x1")
        task_1 = Task(
            id=plan.next_task_id(),
            spec_path="spec-x.spec.md",
            spec_blob_sha="sha-x1",
            name="task-1",
            description="Task 1",
            status=TaskStatus.BACKLOG,
        )
        task_2 = Task(
            id=plan.next_task_id(),
            spec_path="spec-x.spec.md",
            spec_blob_sha="sha-x1",
            name="task-2",
            description="Task 2 depends on task 1",
            status=TaskStatus.BACKLOG,
            depends_on=[task_1.id],
        )
        plan.add_tasks(sp_x, [task_1, task_2])

        spec_source.add_spec("spec-z.spec.md", "sha-z2")

        reconciler.run_cycle()

        assert task_2.status != TaskStatus.FAILED
        assert observer.calls_for("dependency_invalidated") == []

    def test_in_progress_dependent_task_cancelled_on_supersede(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        plan = plan_store.get_plan()

        sp_y = plan.add_spec("spec-y.spec.md", "sha-y1")
        sp_y.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-y.spec.md", "sha-y1")
        workspace_manager.create_delivery_workspace("sha-y1")
        task_a = Task(
            id=plan.next_task_id(),
            spec_path="spec-y.spec.md",
            spec_blob_sha="sha-y1",
            name="task-A",
            description="Task A in spec Y",
            status=TaskStatus.COMPLETE,
        )
        plan.add_tasks(sp_y, [task_a])

        sp_x = plan.add_spec("spec-x.spec.md", "sha-x1")
        sp_x.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-x.spec.md", "sha-x1")
        workspace_manager.create_delivery_workspace("sha-x1")
        handle = AgentHandle(id="agent-dep-task")
        agent_runtime.set_poll_result(handle, PollResult(status=AgentStatus.RUNNING))
        task_b = Task(
            id=plan.next_task_id(),
            spec_path="spec-x.spec.md",
            spec_blob_sha="sha-x1",
            name="task-B",
            description="Task B depends on A",
            status=TaskStatus.IN_PROGRESS,
            agent_handle=handle,
            depends_on=[task_a.id],
        )
        plan.add_tasks(sp_x, [task_b])

        spec_source.add_spec("spec-y.spec.md", "sha-y2")

        reconciler.run_cycle()

        assert task_b.status == TaskStatus.FAILED
        assert agent_runtime.is_cancelled(handle)
        cancelled = observer.calls_for("agent_cancelled")
        dep_cancelled = [
            c
            for c in cancelled
            if c["reason"] == CancellationReason.DEPENDENCY_INVALIDATED
        ]
        assert len(dep_cancelled) == 1
        assert dep_cancelled[0]["task_id"] == task_b.id

    def test_redecomposition_receives_updated_task_state(
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
            max_redecompositions=1,
        )
        plan = plan_store.get_plan()

        sp_y = plan.add_spec("spec-y.spec.md", "sha-y1")
        sp_y.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-y.spec.md", "sha-y1")
        workspace_manager.create_delivery_workspace("sha-y1")
        task_a = Task(
            id=plan.next_task_id(),
            spec_path="spec-y.spec.md",
            spec_blob_sha="sha-y1",
            name="task-A",
            description="Task A in spec Y",
            status=TaskStatus.BACKLOG,
        )
        plan.add_tasks(sp_y, [task_a])

        sp_x = plan.add_spec("spec-x.spec.md", "sha-x1")
        sp_x.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-x.spec.md", "sha-x1")
        workspace_manager.create_delivery_workspace("sha-x1")
        task_b = Task(
            id=plan.next_task_id(),
            spec_path="spec-x.spec.md",
            spec_blob_sha="sha-x1",
            name="task-B",
            description="Task B depends on A",
            status=TaskStatus.BACKLOG,
            depends_on=[task_a.id],
        )
        plan.add_tasks(sp_x, [task_b])

        spec_source.add_spec("spec-y.spec.md", "sha-y2")
        agent_runtime.set_decomposition_result(
            [
                ProposedTask(
                    name="task-A-v2",
                    description="New task A for spec Y v2",
                    spec_path="spec-y.spec.md",
                    spec_blob_sha="sha-y2",
                ),
            ]
        )

        reconciler.run_cycle()

        assert sp_x.status == SpecPlanStatus.OUT_OF_SYNC

        agent_runtime.set_decomposition_result(
            [
                ProposedTask(
                    name="task-B-v2",
                    description="Revised task B",
                    spec_path="spec-x.spec.md",
                    spec_blob_sha="sha-x1",
                    depends_on=["task-A-v2"],
                ),
            ]
        )

        reconciler.run_cycle()

        assert len(agent_runtime.decomposition_calls) == 2
        _, existing_tasks, _ = agent_runtime.decomposition_calls[1]
        spec_y_tasks = [t for t in existing_tasks if t.spec_path == "spec-y.spec.md"]
        assert len(spec_y_tasks) > 0
        assert all(t.spec_blob_sha == "sha-y2" for t in spec_y_tasks)

    def test_multiple_dependents_all_invalidated(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        plan = plan_store.get_plan()

        sp_y = plan.add_spec("spec-y.spec.md", "sha-y1")
        sp_y.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-y.spec.md", "sha-y1")
        workspace_manager.create_delivery_workspace("sha-y1")
        task_a = Task(
            id=plan.next_task_id(),
            spec_path="spec-y.spec.md",
            spec_blob_sha="sha-y1",
            name="task-A",
            description="Task A",
            status=TaskStatus.BACKLOG,
        )
        plan.add_tasks(sp_y, [task_a])

        sp_x = plan.add_spec("spec-x.spec.md", "sha-x1")
        sp_x.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-x.spec.md", "sha-x1")
        workspace_manager.create_delivery_workspace("sha-x1")
        task_b1 = Task(
            id=plan.next_task_id(),
            spec_path="spec-x.spec.md",
            spec_blob_sha="sha-x1",
            name="task-B1",
            description="First dependent",
            status=TaskStatus.BACKLOG,
            depends_on=[task_a.id],
        )
        task_b2 = Task(
            id=plan.next_task_id(),
            spec_path="spec-x.spec.md",
            spec_blob_sha="sha-x1",
            name="task-B2",
            description="Second dependent",
            status=TaskStatus.BACKLOG,
            depends_on=[task_a.id],
        )
        plan.add_tasks(sp_x, [task_b1, task_b2])

        spec_source.add_spec("spec-y.spec.md", "sha-y2")

        reconciler.run_cycle()

        assert task_b1.status == TaskStatus.FAILED
        assert task_b2.status == TaskStatus.FAILED
        dep_events = observer.calls_for("dependency_invalidated")
        assert len(dep_events) == 2
        invalidated_ids = {e["task_id"] for e in dep_events}
        assert invalidated_ids == {task_b1.id, task_b2.id}

    def test_mixed_deps_invalidated_when_cross_spec_dep_superseded(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        plan = plan_store.get_plan()

        sp_y = plan.add_spec("spec-y.spec.md", "sha-y1")
        sp_y.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-y.spec.md", "sha-y1")
        workspace_manager.create_delivery_workspace("sha-y1")
        task_a = Task(
            id=plan.next_task_id(),
            spec_path="spec-y.spec.md",
            spec_blob_sha="sha-y1",
            name="task-A",
            description="Cross-spec task",
            status=TaskStatus.BACKLOG,
        )
        plan.add_tasks(sp_y, [task_a])

        sp_x = plan.add_spec("spec-x.spec.md", "sha-x1")
        sp_x.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-x.spec.md", "sha-x1")
        workspace_manager.create_delivery_workspace("sha-x1")
        task_local = Task(
            id=plan.next_task_id(),
            spec_path="spec-x.spec.md",
            spec_blob_sha="sha-x1",
            name="task-local",
            description="Local task",
            status=TaskStatus.COMPLETE,
        )
        task_c = Task(
            id=plan.next_task_id(),
            spec_path="spec-x.spec.md",
            spec_blob_sha="sha-x1",
            name="task-C",
            description="Depends on both local and cross-spec",
            status=TaskStatus.BACKLOG,
            depends_on=[task_local.id, task_a.id],
        )
        plan.add_tasks(sp_x, [task_local, task_c])

        spec_source.add_spec("spec-y.spec.md", "sha-y2")

        reconciler.run_cycle()

        assert task_c.status == TaskStatus.FAILED
        dep_events = observer.calls_for("dependency_invalidated")
        assert len(dep_events) == 1
        assert dep_events[0]["task_id"] == task_c.id
        assert dep_events[0]["dependency_task_id"] == task_a.id

    def test_failed_spec_with_failed_task_stays_blocked(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        plan = plan_store.get_plan()

        sp_y = plan.add_spec("spec-y.spec.md", "sha-y1")
        sp_y.status = SpecPlanStatus.FAILED
        spec_source.add_spec("spec-y.spec.md", "sha-y1")
        workspace_manager.create_delivery_workspace("sha-y1")
        task_a = Task(
            id=plan.next_task_id(),
            spec_path="spec-y.spec.md",
            spec_blob_sha="sha-y1",
            name="task-A",
            description="Task A in Failed spec",
            status=TaskStatus.FAILED,
        )
        plan.add_tasks(sp_y, [task_a])

        sp_x = plan.add_spec("spec-x.spec.md", "sha-x1")
        sp_x.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-x.spec.md", "sha-x1")
        workspace_manager.create_delivery_workspace("sha-x1")
        task_b = Task(
            id=plan.next_task_id(),
            spec_path="spec-x.spec.md",
            spec_blob_sha="sha-x1",
            name="task-B",
            description="Depends on task A in Failed spec",
            status=TaskStatus.BACKLOG,
            depends_on=[task_a.id],
        )
        plan.add_tasks(sp_x, [task_b])

        reconciler.run_cycle()

        assert task_b.status == TaskStatus.BACKLOG
        assert observer.calls_for("dependency_invalidated") == []

    def test_all_invalid_deps_reported(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        plan = plan_store.get_plan()

        sp_y = plan.add_spec("spec-y.spec.md", "sha-y1")
        sp_y.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-y.spec.md", "sha-y1")
        workspace_manager.create_delivery_workspace("sha-y1")
        task_a1 = Task(
            id=plan.next_task_id(),
            spec_path="spec-y.spec.md",
            spec_blob_sha="sha-y1",
            name="task-A1",
            description="Task A1",
            status=TaskStatus.BACKLOG,
        )
        task_a2 = Task(
            id=plan.next_task_id(),
            spec_path="spec-y.spec.md",
            spec_blob_sha="sha-y1",
            name="task-A2",
            description="Task A2",
            status=TaskStatus.BACKLOG,
        )
        plan.add_tasks(sp_y, [task_a1, task_a2])

        sp_x = plan.add_spec("spec-x.spec.md", "sha-x1")
        sp_x.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-x.spec.md", "sha-x1")
        workspace_manager.create_delivery_workspace("sha-x1")
        task_b = Task(
            id=plan.next_task_id(),
            spec_path="spec-x.spec.md",
            spec_blob_sha="sha-x1",
            name="task-B",
            description="Depends on both A1 and A2",
            status=TaskStatus.BACKLOG,
            depends_on=[task_a1.id, task_a2.id],
        )
        plan.add_tasks(sp_x, [task_b])

        spec_source.add_spec("spec-y.spec.md", "sha-y2")

        reconciler.run_cycle()

        assert task_b.status == TaskStatus.FAILED
        dep_events = observer.calls_for("dependency_invalidated")
        assert len(dep_events) == 2
        reported_dep_ids = {e["dependency_task_id"] for e in dep_events}
        assert reported_dep_ids == {task_a1.id, task_a2.id}
        task_events = [
            e for e in task_b.events if e.reason == EventReason.DEPENDENCY_INVALIDATED
        ]
        assert len(task_events) == 1
        assert task_events[0].count == 2

    def test_blocked_task_invalidated_when_failed_spec_later_superseded(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp_y, sp_x, task_a, task_b = _build_cross_spec_scenario(
            plan_store, spec_source, workspace_manager
        )
        sp_y.status = SpecPlanStatus.FAILED

        reconciler.run_cycle()

        assert task_b.status == TaskStatus.BACKLOG
        assert observer.calls_for("dependency_invalidated") == []

        spec_source.add_spec("spec-y.spec.md", "sha-y2")
        observer.calls.clear()

        reconciler.run_cycle()

        assert task_b.status == TaskStatus.FAILED
        dep_events = observer.calls_for("dependency_invalidated")
        assert len(dep_events) == 1
        assert dep_events[0]["task_id"] == task_b.id

    def test_redecomposition_resolves_new_dependency_ids(
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
            max_redecompositions=1,
        )
        plan = plan_store.get_plan()

        sp_y = plan.add_spec("spec-y.spec.md", "sha-y1")
        sp_y.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-y.spec.md", "sha-y1")
        workspace_manager.create_delivery_workspace("sha-y1")
        task_a = Task(
            id=plan.next_task_id(),
            spec_path="spec-y.spec.md",
            spec_blob_sha="sha-y1",
            name="task-A",
            description="Task A",
            status=TaskStatus.BACKLOG,
        )
        plan.add_tasks(sp_y, [task_a])

        sp_x = plan.add_spec("spec-x.spec.md", "sha-x1")
        sp_x.status = SpecPlanStatus.RECONCILING
        spec_source.add_spec("spec-x.spec.md", "sha-x1")
        workspace_manager.create_delivery_workspace("sha-x1")
        task_b = Task(
            id=plan.next_task_id(),
            spec_path="spec-x.spec.md",
            spec_blob_sha="sha-x1",
            name="task-B",
            description="Depends on A",
            status=TaskStatus.BACKLOG,
            depends_on=[task_a.id],
        )
        plan.add_tasks(sp_x, [task_b])

        spec_source.add_spec("spec-y.spec.md", "sha-y2")
        agent_runtime.set_decomposition_result(
            [
                ProposedTask(
                    name="task-A-v2",
                    description="New A",
                    spec_path="spec-y.spec.md",
                    spec_blob_sha="sha-y2",
                ),
            ]
        )

        reconciler.run_cycle()

        agent_runtime.set_decomposition_result(
            [
                ProposedTask(
                    name="task-B-v2",
                    description="New B",
                    spec_path="spec-x.spec.md",
                    spec_blob_sha="sha-x1",
                    depends_on=["task-A-v2"],
                ),
            ]
        )

        reconciler.run_cycle()

        new_tasks = [t for t in sp_x.tasks if t.name == "task-B-v2"]
        assert len(new_tasks) == 1
        task_a_v2 = next(
            t
            for sp in plan_store.get_plan().spec_plans
            if not sp.superseded
            for t in sp.tasks
            if t.name == "task-A-v2"
        )
        assert task_a_v2.id in new_tasks[0].depends_on


class TestIntegrationSummary:
    def test_compose_called_before_integrate(
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

        assert len(agent_runtime.compose_summary_calls) == 1
        assert len(workspace_manager.integrations) == 1

    def test_compose_receives_correct_context(
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
            spec_content="# Auth Spec\nRequirements here",
        )
        agent_runtime.set_poll_result(
            handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="All requirements verified",
            ),
        )

        reconciler.run_cycle()

        spec_content, task_summaries, rationale = agent_runtime.compose_summary_calls[0]
        assert spec_content == "# Auth Spec\nRequirements here"
        assert rationale == "All requirements verified"
        assert len(task_summaries) == 2
        names = {name for name, _ in task_summaries}
        descriptions = {desc for _, desc in task_summaries}
        assert names == {"task-1", "task-2"}
        assert descriptions == {"Task 1 description", "Task 2 description"}

    def test_generated_title_and_body_passed_to_integrate(
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
        agent_runtime.set_integration_summary(
            IntegrationSummary(
                title="Implement authentication",
                body="Added auth module with login and logout",
            )
        )

        reconciler.run_cycle()

        assert len(workspace_manager.integrations) == 1
        _, _, title, body = workspace_manager.integrations[0]
        assert title == "Implement authentication"
        assert body == "Added auth module with login and logout"

    def test_compose_failure_prevents_integration(
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
        agent_runtime.set_integration_summary_error(RuntimeError("Agent unavailable"))

        reconciler.run_cycle()

        assert len(workspace_manager.integrations) == 0
        assert sp.status == SpecPlanStatus.VERIFYING

    def test_compose_failure_fires_trunk_integration_failed(
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
        agent_runtime.set_integration_summary_error(RuntimeError("Agent unavailable"))

        reconciler.run_cycle()

        events = observer.calls_for("trunk_integration_failed")
        assert len(events) == 1

    def test_compose_failure_increments_integration_attempts(
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
        agent_runtime.set_integration_summary_error(RuntimeError("Agent unavailable"))

        reconciler.run_cycle()

        assert sp.integration_attempts == 1

    def test_summary_cached_for_integration_retry(
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
        agent_runtime.set_integration_summary(
            IntegrationSummary(title="Auth feature", body="Implements auth")
        )
        workspace_manager._delivery_workspaces.discard("abc123")

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.VERIFYING
        assert len(agent_runtime.compose_summary_calls) == 1

        workspace_manager._delivery_workspaces.add("abc123")

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.PENDING_INTEGRATION
        assert len(agent_runtime.compose_summary_calls) == 1
        _, _, title, body = workspace_manager.integrations[0]
        assert title == "Auth feature"
        assert body == "Implements auth"

    def test_compose_retried_after_compose_failure(
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
        agent_runtime.set_integration_summary_error(RuntimeError("Agent unavailable"))

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.VERIFYING
        assert len(agent_runtime.compose_summary_calls) == 1

        agent_runtime.set_integration_summary(
            IntegrationSummary(title="Auth feature", body="Implements auth")
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.PENDING_INTEGRATION
        assert len(agent_runtime.compose_summary_calls) == 2

    def test_only_complete_tasks_in_summaries(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        plan = plan_store.get_plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        spec_source.add_spec("auth.spec.md", "abc123", content="spec content")
        workspace_manager.create_delivery_workspace("abc123")
        sp.delivery_workspace_id = "delivery/abc123"

        complete_task = Task(
            id=plan.next_task_id(),
            spec_path="auth.spec.md",
            spec_blob_sha="abc123",
            name="done-task",
            description="Completed work",
            status=TaskStatus.COMPLETE,
        )
        failed_task = Task(
            id=plan.next_task_id(),
            spec_path="auth.spec.md",
            spec_blob_sha="abc123",
            name="failed-task",
            description="Failed work",
            status=TaskStatus.FAILED,
        )
        plan.add_tasks(sp, [complete_task, failed_task])
        sp.status = SpecPlanStatus.VERIFYING

        verification_handle = AgentHandle(id="verifier-mix")
        sp.verification_handle = verification_handle
        agent_runtime.set_poll_result(
            verification_handle,
            PollResult(
                status=AgentStatus.COMPLETE,
                verdict=AgentVerdict.PASS,
                rationale="Pass",
            ),
        )

        reconciler.run_cycle()

        _, task_summaries, _ = agent_runtime.compose_summary_calls[0]
        assert len(task_summaries) == 1
        assert task_summaries[0] == ("done-task", "Completed work")


class TestDecompositionFailure:
    def test_failure_records_event_and_stays_out_of_sync(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_error(RuntimeError("agent crashed"))

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = plan.spec_plans[0]
        assert sp.status == SpecPlanStatus.OUT_OF_SYNC
        assert sp.tasks == []

        decomp_events = [
            e for e in sp.events if e.reason == EventReason.DECOMPOSITION_FAILED
        ]
        assert len(decomp_events) == 1
        assert decomp_events[0].count == 1
        assert "agent crashed" in decomp_events[0].message

    def test_failure_fires_decomposition_failed_probe(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_error(RuntimeError("timeout"))

        reconciler.run_cycle()

        probes = observer.calls_for("decomposition_failed")
        assert len(probes) == 1
        assert "timeout" in probes[0]["reason"]
        assert probes[0]["cycle"] == 1

    def test_failure_increments_reconciliation_attempts(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_error(RuntimeError("fail"))

        reconciler.run_cycle()

        sp = plan_store.get_plan().spec_plans[0]
        assert sp.reconciliation_attempts == 1

    def test_repeated_failure_exceeds_convergence_bound(
        self,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        convergence_bound = 3
        reconciler = Reconciler(
            spec_source=spec_source,
            plan_store=plan_store,
            observer=observer,
            agent_runtime=agent_runtime,
            workspace_manager=workspace_manager,
            convergence_bound=convergence_bound,
        )

        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_error(RuntimeError("keeps failing"))

        for _ in range(convergence_bound):
            reconciler.run_cycle()

        sp = plan_store.get_plan().spec_plans[0]
        assert sp.status == SpecPlanStatus.FAILED
        assert sp.reconciliation_attempts == convergence_bound

        failed_probes = observer.calls_for("spec_failed")
        assert len(failed_probes) == 1
        assert failed_probes[0]["spec_path"] == "auth.spec.md"
        assert failed_probes[0]["spec_blob_sha"] == "abc123"

    def test_failure_below_convergence_bound_stays_out_of_sync(
        self,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        convergence_bound = 3
        reconciler = Reconciler(
            spec_source=spec_source,
            plan_store=plan_store,
            observer=observer,
            agent_runtime=agent_runtime,
            workspace_manager=workspace_manager,
            convergence_bound=convergence_bound,
        )

        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_error(RuntimeError("fail"))

        for _ in range(convergence_bound - 1):
            reconciler.run_cycle()

        sp = plan_store.get_plan().spec_plans[0]
        assert sp.status == SpecPlanStatus.OUT_OF_SYNC
        assert sp.reconciliation_attempts == convergence_bound - 1

        decomp_events = [
            e for e in sp.events if e.reason == EventReason.DECOMPOSITION_FAILED
        ]
        assert len(decomp_events) == 1
        assert decomp_events[0].count == convergence_bound - 1

    def test_successful_retry_after_prior_failure(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_error(RuntimeError("transient"))

        reconciler.run_cycle()

        sp = plan_store.get_plan().spec_plans[0]
        assert sp.status == SpecPlanStatus.OUT_OF_SYNC
        assert sp.reconciliation_attempts == 1

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

        sp = plan_store.get_plan().spec_plans[0]
        assert sp.status == SpecPlanStatus.RECONCILING
        assert len(sp.tasks) == 1

        decomp_events = [
            e for e in sp.events if e.reason == EventReason.DECOMPOSITION_FAILED
        ]
        assert len(decomp_events) == 1
        assert decomp_events[0].count == 1

    def test_failed_spec_not_retried_on_next_cycle(
        self,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        reconciler = Reconciler(
            spec_source=spec_source,
            plan_store=plan_store,
            observer=observer,
            agent_runtime=agent_runtime,
            workspace_manager=workspace_manager,
            convergence_bound=1,
        )

        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_error(RuntimeError("fatal"))

        reconciler.run_cycle()

        sp = plan_store.get_plan().spec_plans[0]
        assert sp.status == SpecPlanStatus.FAILED

        observer.calls.clear()
        reconciler.run_cycle()

        assert observer.calls_for("decomposition_started") == []

    def test_no_tasks_created_on_failure(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_error(RuntimeError("crash"))

        reconciler.run_cycle()

        sp = plan_store.get_plan().spec_plans[0]
        assert sp.tasks == []
        assert observer.calls_for("task_created") == []

    def test_multiple_specs_all_receive_failure_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "aaa111")
        spec_source.add_spec("users.spec.md", "bbb222")
        agent_runtime.set_decomposition_error(RuntimeError("batch failure"))

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        assert len(plan.spec_plans) == 2
        for sp in plan.spec_plans:
            assert sp.status == SpecPlanStatus.OUT_OF_SYNC
            assert sp.reconciliation_attempts == 1
            assert sp.tasks == []
            decomp_events = [
                e for e in sp.events if e.reason == EventReason.DECOMPOSITION_FAILED
            ]
            assert len(decomp_events) == 1
            assert "batch failure" in decomp_events[0].message

    def test_cycle_completes_normally_after_decomposition_failure(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        spec_source.add_spec("auth.spec.md", "abc123")
        agent_runtime.set_decomposition_error(RuntimeError("boom"))

        reconciler.run_cycle()

        cycle_completed = observer.calls_for("cycle_completed")
        assert len(cycle_completed) == 1
        assert cycle_completed[0]["cycle"] == 1


class TestCyclicDependencyRejection:
    def test_self_referencing_dependency_rejected(
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
                    name="task-a",
                    description="Self-referencing task",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-a"],
                ),
            ]
        )

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = plan.spec_plans[0]
        assert sp.tasks == []
        assert sp.status == SpecPlanStatus.OUT_OF_SYNC

    def test_direct_cycle_rejected(
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
                    name="task-a",
                    description="A depends on B",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-b"],
                ),
                ProposedTask(
                    name="task-b",
                    description="B depends on A",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-a"],
                ),
            ]
        )

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = plan.spec_plans[0]
        assert sp.tasks == []
        assert sp.status == SpecPlanStatus.OUT_OF_SYNC

    def test_indirect_cycle_rejected(
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
                    name="task-a",
                    description="A depends on C",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-c"],
                ),
                ProposedTask(
                    name="task-b",
                    description="B depends on A",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-a"],
                ),
                ProposedTask(
                    name="task-c",
                    description="C depends on B",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-b"],
                ),
            ]
        )

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = plan.spec_plans[0]
        assert sp.tasks == []
        assert sp.status == SpecPlanStatus.OUT_OF_SYNC

    def test_cyclic_dependency_records_decomposition_failed_event(
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
                    name="task-a",
                    description="A",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-b"],
                ),
                ProposedTask(
                    name="task-b",
                    description="B",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-a"],
                ),
            ]
        )

        reconciler.run_cycle()

        sp = plan_store.get_plan().spec_plans[0]
        decomp_events = [
            e for e in sp.events if e.reason == EventReason.DECOMPOSITION_FAILED
        ]
        assert len(decomp_events) == 1
        assert "cyclic" in decomp_events[0].message.lower()

    def test_cyclic_dependency_fires_decomposition_failed_probe(
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
                    name="task-a",
                    description="A",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-b"],
                ),
                ProposedTask(
                    name="task-b",
                    description="B",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-a"],
                ),
            ]
        )

        reconciler.run_cycle()

        probes = observer.calls_for("decomposition_failed")
        assert len(probes) == 1
        assert "cyclic" in probes[0]["reason"].lower()

    def test_valid_dag_accepted(
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
                    name="task-a",
                    description="A",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                ),
                ProposedTask(
                    name="task-b",
                    description="B depends on A",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-a"],
                ),
                ProposedTask(
                    name="task-c",
                    description="C depends on B",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-b"],
                ),
            ]
        )

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = next(sp for sp in plan.spec_plans if sp.path == "auth.spec.md")
        assert len(sp.tasks) == 3
        assert sp.status == SpecPlanStatus.RECONCILING

    def test_independent_tasks_accepted(
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
                    name="task-a",
                    description="A",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                ),
                ProposedTask(
                    name="task-b",
                    description="B",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                ),
            ]
        )

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = next(sp for sp in plan.spec_plans if sp.path == "auth.spec.md")
        assert len(sp.tasks) == 2
        assert sp.status == SpecPlanStatus.RECONCILING

    def test_diamond_dag_accepted(
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
                    name="task-a",
                    description="A (root)",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                ),
                ProposedTask(
                    name="task-b",
                    description="B depends on A",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-a"],
                ),
                ProposedTask(
                    name="task-c",
                    description="C depends on A",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-a"],
                ),
                ProposedTask(
                    name="task-d",
                    description="D depends on B and C",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-b", "task-c"],
                ),
            ]
        )

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        sp = next(sp for sp in plan.spec_plans if sp.path == "auth.spec.md")
        assert len(sp.tasks) == 4
        assert sp.status == SpecPlanStatus.RECONCILING
        task_d = next(t for t in sp.tasks if t.name == "task-d")
        task_b = next(t for t in sp.tasks if t.name == "task-b")
        task_c = next(t for t in sp.tasks if t.name == "task-c")
        assert set(task_d.depends_on) == {task_b.id, task_c.id}

    def test_cyclic_dependency_increments_reconciliation_attempts(
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
                    name="task-a",
                    description="A",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-a"],
                ),
            ]
        )

        reconciler.run_cycle()

        sp = plan_store.get_plan().spec_plans[0]
        assert sp.reconciliation_attempts == 1

    def test_no_task_created_events_on_cycle(
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
                    name="task-a",
                    description="A",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-b"],
                ),
                ProposedTask(
                    name="task-b",
                    description="B",
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    depends_on=["task-a"],
                ),
            ]
        )

        reconciler.run_cycle()

        assert observer.calls_for("task_created") == []

    def test_cross_spec_cycle_rejected(
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
                    name="task-auth",
                    description="Auth depends on users task",
                    spec_path="auth.spec.md",
                    spec_blob_sha="aaa",
                    depends_on=["task-users"],
                ),
                ProposedTask(
                    name="task-users",
                    description="Users depends on auth task",
                    spec_path="users.spec.md",
                    spec_blob_sha="bbb",
                    depends_on=["task-auth"],
                ),
            ]
        )

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        for sp in plan.spec_plans:
            assert sp.tasks == []
            assert sp.status == SpecPlanStatus.OUT_OF_SYNC


class TestPromptHotReload:
    def test_cycle_calls_rebuild_if_changed(self) -> None:
        prompt_composer = FakePromptComposer()
        reconciler = Reconciler(
            spec_source=FakeSpecSource(),
            plan_store=FakePlanStore(),
            observer=FakeObserver(),
            agent_runtime=FakeAgentRuntime(),
            workspace_manager=FakeWorkspaceManager(),
            prompt_composer=prompt_composer,
        )

        reconciler.run_cycle()

        assert prompt_composer.rebuild_if_changed_count == 1

    def test_cycle_calls_rebuild_if_changed_each_cycle(self) -> None:
        prompt_composer = FakePromptComposer()
        reconciler = Reconciler(
            spec_source=FakeSpecSource(),
            plan_store=FakePlanStore(),
            observer=FakeObserver(),
            agent_runtime=FakeAgentRuntime(),
            workspace_manager=FakeWorkspaceManager(),
            prompt_composer=prompt_composer,
        )

        reconciler.run_cycle()
        reconciler.run_cycle()
        reconciler.run_cycle()

        assert prompt_composer.rebuild_if_changed_count == 3

    def test_cycle_without_composer_does_not_fail(self) -> None:
        reconciler = Reconciler(
            spec_source=FakeSpecSource(),
            plan_store=FakePlanStore(),
            observer=FakeObserver(),
            agent_runtime=FakeAgentRuntime(),
            workspace_manager=FakeWorkspaceManager(),
        )

        reconciler.run_cycle()


def _build_pending_integration_spec_plan(
    plan_store: FakePlanStore,
    spec_source: FakeSpecSource,
    workspace_manager: FakeWorkspaceManager,
    path: str = "auth.spec.md",
    blob_sha: str = "abc123",
    integration_id: str = "https://github.com/example/repo/pull/42",
) -> SpecPlan:
    plan = plan_store.get_plan()
    sp = plan.add_spec(path, blob_sha)
    spec_source.add_spec(path, blob_sha)
    workspace_manager.create_delivery_workspace(blob_sha)
    sp.delivery_workspace_id = f"delivery/{blob_sha}"
    task_id = plan.next_task_id()
    plan.add_tasks(
        sp,
        [
            Task(
                id=task_id,
                spec_path=path,
                spec_blob_sha=blob_sha,
                name="task-1",
                description="Implement auth",
                status=TaskStatus.COMPLETE,
                workspace_id=f"task/{blob_sha}/{task_id}",
            ),
        ],
    )
    sp.status = SpecPlanStatus.PENDING_INTEGRATION
    sp.integration_id = integration_id
    return sp


class TestIntegrationPolling:
    def test_merged_transitions_to_synced(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.MERGED),
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.SYNCED

    def test_merged_records_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.MERGED),
        )

        reconciler.run_cycle()

        merged_events = [
            e for e in sp.events if e.reason == EventReason.INTEGRATION_MERGED
        ]
        assert len(merged_events) == 1

    def test_merged_fires_spec_synced_observer(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.MERGED),
        )

        reconciler.run_cycle()

        events = observer.calls_for("spec_synced")
        assert len(events) == 1
        assert events[0]["spec_path"] == "auth.spec.md"

    def test_merged_resets_integration_attempts(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        sp.integration_attempts = 2
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.MERGED),
        )

        reconciler.run_cycle()

        assert sp.integration_attempts == 0

    def test_pending_remains_pending(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.PENDING_INTEGRATION

    def test_pending_fires_trunk_integration_polled_observer(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )

        reconciler.run_cycle()

        events = observer.calls_for("trunk_integration_polled")
        assert len(events) == 1
        assert events[0]["integration_id"] == sp.integration_id
        assert events[0]["status"] == IntegrationPollStatus.PENDING

    def test_closed_transitions_to_failed(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.CLOSED),
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.FAILED

    def test_closed_records_pr_closed_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.CLOSED),
        )

        reconciler.run_cycle()

        pr_closed_events = [e for e in sp.events if e.reason == EventReason.PR_CLOSED]
        assert len(pr_closed_events) == 1

    def test_closed_fires_spec_failed_observer(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.CLOSED),
        )

        reconciler.run_cycle()

        events = observer.calls_for("spec_failed")
        assert len(events) == 1
        assert "closed" in events[0]["reason"].lower()

    def test_failed_increments_attempts(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.FAILED),
        )

        reconciler.run_cycle()

        assert sp.integration_attempts == 1
        assert sp.status == SpecPlanStatus.PENDING_INTEGRATION

    def test_failed_exhaustion_transitions_to_failed(
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
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        sp.integration_attempts = 1
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.FAILED),
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.FAILED
        assert sp.integration_attempts == 2

    def test_failed_exhaustion_fires_spec_failed(
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
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.FAILED),
        )

        reconciler.run_cycle()

        events = observer.calls_for("spec_failed")
        assert len(events) == 1
        assert "retry limit" in events[0]["reason"].lower()


class TestIntegrationConflictRebase:
    def test_conflict_with_successful_rebase_transitions_to_verifying(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.CONFLICT),
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.VERIFYING

    def test_conflict_rebase_launches_verification(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
        observer: FakeObserver,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.CONFLICT),
        )

        reconciler.run_cycle()

        assert sp.verification_handle is not None
        events = observer.calls_for("verification_launched")
        assert len(events) == 1

    def test_conflict_rebase_records_delivery_rebased_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.CONFLICT),
        )

        reconciler.run_cycle()

        rebased_events = [
            e for e in sp.events if e.reason == EventReason.DELIVERY_REBASED
        ]
        assert len(rebased_events) == 1

    def test_conflict_rebase_fires_observer_probes(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.CONFLICT),
        )

        reconciler.run_cycle()

        started = observer.calls_for("delivery_rebase_started")
        assert len(started) == 1
        completed = observer.calls_for("delivery_rebase_completed")
        assert len(completed) == 1

    def test_conflict_rebase_increments_integration_attempts(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.CONFLICT),
        )

        reconciler.run_cycle()

        assert sp.integration_attempts == 1

    def test_conflict_rebase_failure_transitions_to_out_of_sync(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.CONFLICT),
        )
        workspace_manager.set_rebase_result(
            "abc123",
            RebaseResult(
                outcome=RebaseOutcome.CONFLICT,
                conflict_details="Conflicting changes in auth.py",
            ),
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.OUT_OF_SYNC

    def test_conflict_rebase_failure_records_event(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.CONFLICT),
        )
        workspace_manager.set_rebase_result(
            "abc123",
            RebaseResult(
                outcome=RebaseOutcome.CONFLICT,
                conflict_details="Conflicting changes in auth.py",
            ),
        )

        reconciler.run_cycle()

        rebase_failed = [e for e in sp.events if e.reason == EventReason.REBASE_FAILED]
        assert len(rebase_failed) == 1
        assert "Conflicting changes" in rebase_failed[0].message

    def test_conflict_rebase_failure_fires_observer(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.CONFLICT),
        )
        workspace_manager.set_rebase_result(
            "abc123",
            RebaseResult(
                outcome=RebaseOutcome.CONFLICT,
                conflict_details="Conflicting changes",
            ),
        )

        reconciler.run_cycle()

        events = observer.calls_for("delivery_rebase_conflict")
        assert len(events) == 1

    def test_post_rebase_verification_receives_rebase_context(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.CONFLICT),
        )
        workspace_manager.set_rebase_result(
            "abc123",
            RebaseResult(
                outcome=RebaseOutcome.SUCCESS,
                trunk_changes="Modified auth.py with new middleware",
            ),
        )

        reconciler.run_cycle()

        assert len(agent_runtime.launched_verifications) == 1
        _, _, _, _, rebase_ctx = agent_runtime.launched_verifications[0]
        assert rebase_ctx is not None
        assert isinstance(rebase_ctx, RebaseContext)
        assert rebase_ctx.trunk_changes == "Modified auth.py with new middleware"

    def test_post_rebase_verification_without_trunk_changes_still_sends_context(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        agent_runtime: FakeAgentRuntime,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.CONFLICT),
        )
        workspace_manager.set_rebase_result(
            "abc123",
            RebaseResult(outcome=RebaseOutcome.SUCCESS),
        )

        reconciler.run_cycle()

        assert len(agent_runtime.launched_verifications) == 1
        _, _, _, _, rebase_ctx = agent_runtime.launched_verifications[0]
        assert rebase_ctx is not None
        assert isinstance(rebase_ctx, RebaseContext)

    def test_initial_verification_has_no_rebase_context(
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
        _, _, _, _, rebase_ctx = agent_runtime.launched_verifications[0]
        assert rebase_ctx is None

    def test_superseded_pending_integration_not_polled(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        sp.superseded = True

        reconciler.run_cycle()

        assert observer.calls_for("trunk_integration_polled") == []

    def test_no_integration_id_skips_polling(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        sp.integration_id = None

        reconciler.run_cycle()

        assert observer.calls_for("trunk_integration_polled") == []

    def test_poll_exception_is_swallowed(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        original = workspace_manager.poll_integration

        def failing_poll(integration_id: str) -> IntegrationPollResult:
            raise RuntimeError("Network error")

        workspace_manager.poll_integration = failing_poll  # type: ignore[assignment]

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.PENDING_INTEGRATION

        workspace_manager.poll_integration = original  # type: ignore[assignment]

    def test_crash_recovery_preserves_pending_integration(
        self,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )

        reconciler = Reconciler(
            spec_source=spec_source,
            plan_store=plan_store,
            observer=observer,
            agent_runtime=agent_runtime,
            workspace_manager=workspace_manager,
        )

        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.MERGED),
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.SYNCED

    def test_full_flow_verification_to_pending_to_synced(
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
        assert sp.status == SpecPlanStatus.PENDING_INTEGRATION

        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.MERGED),
        )

        reconciler.run_cycle()
        assert sp.status == SpecPlanStatus.SYNCED

    def test_same_cycle_pending_integration_not_polled(
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
        workspace_manager.set_poll_integration_result(
            "https://github.com/example/repo/pull/fake-abc123",
            IntegrationPollResult(status=IntegrationPollStatus.MERGED),
        )

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.PENDING_INTEGRATION
        assert observer.calls_for("trunk_integration_polled") == []

    def test_rebase_exception_transitions_to_out_of_sync(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )
        workspace_manager.set_poll_integration_result(
            sp.integration_id,  # type: ignore[arg-type]
            IntegrationPollResult(status=IntegrationPollStatus.CONFLICT),
        )
        original = workspace_manager.rebase_delivery

        def failing_rebase(blob_sha: str) -> RebaseResult:
            raise RuntimeError("Git error during rebase")

        workspace_manager.rebase_delivery = failing_rebase  # type: ignore[assignment]

        reconciler.run_cycle()

        assert sp.status == SpecPlanStatus.OUT_OF_SYNC
        rebase_failed = [e for e in sp.events if e.reason == EventReason.REBASE_FAILED]
        assert len(rebase_failed) == 1
        events = observer.calls_for("delivery_rebase_conflict")
        assert len(events) == 1

        workspace_manager.rebase_delivery = original  # type: ignore[assignment]

    def test_new_sha_during_pending_integration_supersedes(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
        workspace_manager: FakeWorkspaceManager,
        observer: FakeObserver,
    ) -> None:
        sp = _build_pending_integration_spec_plan(
            plan_store, spec_source, workspace_manager
        )

        spec_source.add_spec("auth.spec.md", "def456")

        reconciler.run_cycle()

        assert sp.superseded is True
        superseded_events = observer.calls_for("spec_superseded")
        assert len(superseded_events) == 1
