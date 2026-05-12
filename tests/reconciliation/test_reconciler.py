from __future__ import annotations

import pytest

from hyperloop.reconciliation.models import SpecPlanStatus, Task, TaskStatus
from hyperloop.reconciliation.models.agent_handle import AgentHandle
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
    def test_new_spec_added_as_out_of_sync(
        self,
        reconciler: Reconciler,
        spec_source: FakeSpecSource,
        plan_store: FakePlanStore,
    ) -> None:
        spec_source.add_spec("users.spec.md", "abc123")

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        assert len(plan.spec_plans) == 1
        assert plan.spec_plans[0].path == "users.spec.md"
        assert plan.spec_plans[0].blob_sha == "abc123"
        assert plan.spec_plans[0].status == SpecPlanStatus.OUT_OF_SYNC

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
    ) -> None:
        plan_store.get_plan().add_spec("auth.spec.md", "abc123")
        spec_source.add_spec("auth.spec.md", "def456")

        reconciler.run_cycle()

        plan = plan_store.get_plan()
        old = [sp for sp in plan.spec_plans if sp.blob_sha == "abc123"]
        new = [sp for sp in plan.spec_plans if sp.blob_sha == "def456"]
        assert len(old) == 1
        assert old[0].superseded is True
        assert len(new) == 1
        assert new[0].superseded is False
        assert new[0].status == SpecPlanStatus.OUT_OF_SYNC

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
            ),
            Task(
                id=id2,
                spec_path=path,
                spec_blob_sha=blob_sha,
                name="T2",
                description="D2",
                status=TaskStatus.IN_PROGRESS,
                agent_handle=handle_b,
            ),
        ],
    )
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
        assert all(c["reason"] == "superseded" for c in cancelled)

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
