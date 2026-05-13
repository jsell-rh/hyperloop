from __future__ import annotations

import pytest

from hyperloop.reconciliation.models.agent_handle import AgentHandle
from hyperloop.reconciliation.models.halt_reason import HaltReason
from hyperloop.reconciliation.models.plan import Plan
from hyperloop.reconciliation.models.spec_plan import SpecPlanStatus
from hyperloop.reconciliation.models.task import Task, TaskStatus
from hyperloop.reconciliation.reconciler import Reconciler
from tests.reconciliation.fakes.fake_agent_runtime import FakeAgentRuntime
from tests.reconciliation.fakes.fake_observer import FakeObserver
from tests.reconciliation.fakes.fake_plan_store import FakePlanStore
from tests.reconciliation.fakes.fake_spec_source import FakeSpecSource
from tests.reconciliation.fakes.fake_workspace_manager import FakeWorkspaceManager


class AutoStopSpecSource(FakeSpecSource):
    """Spec source that stops the reconciler after a configured number of syncs."""

    def __init__(self) -> None:
        super().__init__()
        self._reconciler: Reconciler | None = None
        self._stop_after: int = 1

    def configure_stop(self, reconciler: Reconciler, stop_after: int) -> None:
        self._reconciler = reconciler
        self._stop_after = stop_after

    def sync(self) -> None:
        super().sync()
        if self._reconciler is not None and self.sync_count >= self._stop_after:
            self._reconciler.stop()


@pytest.fixture()
def spec_source() -> AutoStopSpecSource:
    return AutoStopSpecSource()


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


def _make_reconciler(
    spec_source: AutoStopSpecSource,
    plan_store: FakePlanStore,
    observer: FakeObserver,
    agent_runtime: FakeAgentRuntime,
    workspace_manager: FakeWorkspaceManager,
    *,
    stop_after: int = 1,
) -> Reconciler:
    reconciler = Reconciler(
        spec_source=spec_source,
        plan_store=plan_store,
        observer=observer,
        agent_runtime=agent_runtime,
        workspace_manager=workspace_manager,
        cycle_interval_seconds=0,
    )
    spec_source.configure_stop(reconciler, stop_after=stop_after)
    return reconciler


class TestCrashRecovery:
    def test_no_stale_skips_recovery_probes(
        self,
        spec_source: AutoStopSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        reconciler = _make_reconciler(
            spec_source, plan_store, observer, agent_runtime, workspace_manager
        )

        reconciler.run()

        assert observer.calls_for("crash_recovery_started") == []

    def test_detects_and_cancels_stale_agents(
        self,
        spec_source: AutoStopSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        stale_handle = AgentHandle(id="stale-1")
        agent_runtime.set_stale([stale_handle])

        reconciler = _make_reconciler(
            spec_source, plan_store, observer, agent_runtime, workspace_manager
        )
        reconciler.run()

        assert agent_runtime.is_cancelled(stale_handle)

    def test_emits_crash_recovery_started_probe(
        self,
        spec_source: AutoStopSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        agent_runtime.set_stale([AgentHandle(id="stale-1"), AgentHandle(id="stale-2")])

        reconciler = _make_reconciler(
            spec_source, plan_store, observer, agent_runtime, workspace_manager
        )
        reconciler.run()

        recovery_calls = observer.calls_for("crash_recovery_started")
        assert len(recovery_calls) == 1
        assert recovery_calls[0]["stale_agent_count"] == 2

    def test_emits_stale_agent_detected_for_matching_tasks(
        self,
        spec_source: AutoStopSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        stale_handle = AgentHandle(id="stale-task-agent")
        agent_runtime.set_stale([stale_handle])

        plan = Plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        task = Task(
            id=1,
            spec_path="auth.spec.md",
            spec_blob_sha="abc123",
            name="Implement auth",
            description="Add auth module",
            status=TaskStatus.IN_PROGRESS,
            agent_handle=stale_handle,
        )
        plan.add_tasks(sp, [task])
        plan_store = FakePlanStore(plan)

        spec_source.add_spec("auth.spec.md", "abc123")
        reconciler = _make_reconciler(
            spec_source, plan_store, observer, agent_runtime, workspace_manager
        )
        reconciler.run()

        stale_calls = observer.calls_for("stale_agent_detected")
        assert len(stale_calls) == 1
        assert stale_calls[0]["task_id"] == 1
        assert stale_calls[0]["spec_path"] == "auth.spec.md"

    def test_resets_in_progress_tasks_to_backlog(
        self,
        spec_source: AutoStopSpecSource,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        stale_handle = AgentHandle(id="stale-agent")
        agent_runtime.set_stale([stale_handle])

        plan = Plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        task = Task(
            id=1,
            spec_path="auth.spec.md",
            spec_blob_sha="abc123",
            name="Implement auth",
            description="Add auth module",
            status=TaskStatus.IN_PROGRESS,
            agent_handle=stale_handle,
        )
        plan.add_tasks(sp, [task])
        plan_store = FakePlanStore(plan)

        spec_source.add_spec("auth.spec.md", "abc123", "spec content")
        reconciler = _make_reconciler(
            spec_source, plan_store, observer, agent_runtime, workspace_manager
        )
        reconciler.run()

        dispatched = observer.calls_for("task_dispatched")
        assert any(d["task_id"] == 1 for d in dispatched)

    def test_resets_verifying_spec_plans(
        self,
        spec_source: AutoStopSpecSource,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        verification_handle = AgentHandle(id="verify-agent")
        agent_runtime.set_stale([verification_handle])

        plan = Plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        sp.status = SpecPlanStatus.VERIFYING
        sp.verification_handle = verification_handle
        plan_store = FakePlanStore(plan)

        spec_source.add_spec("auth.spec.md", "abc123", "spec content")
        reconciler = _make_reconciler(
            spec_source, plan_store, observer, agent_runtime, workspace_manager
        )
        reconciler.run()

        launched = observer.calls_for("verification_launched")
        assert len(launched) >= 1
        assert launched[0]["spec_path"] == "auth.spec.md"

    def test_persists_recovered_plan(
        self,
        spec_source: AutoStopSpecSource,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        agent_runtime.set_stale([AgentHandle(id="stale-1")])

        plan = Plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        task = Task(
            id=1,
            spec_path="auth.spec.md",
            spec_blob_sha="abc123",
            name="Implement auth",
            description="Add auth module",
            status=TaskStatus.IN_PROGRESS,
            agent_handle=AgentHandle(id="stale-1"),
        )
        plan.add_tasks(sp, [task])
        plan_store = FakePlanStore(plan)

        spec_source.add_spec("auth.spec.md", "abc123")
        reconciler = _make_reconciler(
            spec_source, plan_store, observer, agent_runtime, workspace_manager
        )
        reconciler.run()

        # write_plan called during recovery + once per cycle
        assert plan_store.write_count >= 2

    def test_stale_without_matching_task_is_cancelled(
        self,
        spec_source: AutoStopSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        stale_handle = AgentHandle(id="unknown-agent")
        agent_runtime.set_stale([stale_handle])

        reconciler = _make_reconciler(
            spec_source, plan_store, observer, agent_runtime, workspace_manager
        )
        reconciler.run()

        assert agent_runtime.is_cancelled(stale_handle)
        assert observer.calls_for("stale_agent_detected") == []

    def test_mixed_stale_matching_and_non_matching(
        self,
        spec_source: AutoStopSpecSource,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        matching_handle = AgentHandle(id="task-agent")
        non_matching_handle = AgentHandle(id="stale-agent")
        agent_runtime.set_stale([matching_handle, non_matching_handle])

        plan = Plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        task = Task(
            id=1,
            spec_path="auth.spec.md",
            spec_blob_sha="abc123",
            name="Implement auth",
            description="Add auth module",
            status=TaskStatus.IN_PROGRESS,
            agent_handle=matching_handle,
        )
        plan.add_tasks(sp, [task])
        plan_store = FakePlanStore(plan)

        spec_source.add_spec("auth.spec.md", "abc123")
        reconciler = _make_reconciler(
            spec_source, plan_store, observer, agent_runtime, workspace_manager
        )
        reconciler.run()

        assert agent_runtime.is_cancelled(matching_handle)
        assert agent_runtime.is_cancelled(non_matching_handle)

        stale_calls = observer.calls_for("stale_agent_detected")
        assert len(stale_calls) == 1
        assert stale_calls[0]["task_id"] == 1

        recovery_calls = observer.calls_for("crash_recovery_started")
        assert recovery_calls[0]["stale_agent_count"] == 2

    def test_cancel_exception_during_recovery_is_swallowed(
        self,
        spec_source: AutoStopSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        stale_handle = AgentHandle(id="broken-agent")

        class FailingCancelRuntime(FakeAgentRuntime):
            def cancel(self, handle: AgentHandle) -> None:
                if handle.id == "broken-agent":
                    raise RuntimeError("Agent process not found")
                super().cancel(handle)

        agent_runtime = FailingCancelRuntime()
        agent_runtime.set_stale([stale_handle])

        reconciler = _make_reconciler(
            spec_source, plan_store, observer, agent_runtime, workspace_manager
        )
        reconciler.run()

        started_calls = observer.calls_for("reconciler_started")
        assert len(started_calls) == 1


class TestReconcilerRun:
    def test_emits_reconciler_started_with_spec_count(
        self,
        spec_source: AutoStopSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        plan.add_spec("users.spec.md", "def456")
        plan_store = FakePlanStore(plan)

        spec_source.add_spec("auth.spec.md", "abc123")
        spec_source.add_spec("users.spec.md", "def456")

        reconciler = _make_reconciler(
            spec_source, plan_store, observer, agent_runtime, workspace_manager
        )
        reconciler.run()

        started_calls = observer.calls_for("reconciler_started")
        assert len(started_calls) == 1
        assert started_calls[0]["spec_count"] == 2
        assert started_calls[0]["cycle"] == 0

    def test_reconciler_started_before_first_cycle(
        self,
        spec_source: AutoStopSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        reconciler = _make_reconciler(
            spec_source, plan_store, observer, agent_runtime, workspace_manager
        )
        reconciler.run()

        method_order = [c.method for c in observer.calls]
        started_idx = method_order.index("reconciler_started")
        cycle_started_idx = method_order.index("cycle_started")
        assert started_idx < cycle_started_idx

    def test_runs_multiple_cycles(
        self,
        spec_source: AutoStopSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        reconciler = _make_reconciler(
            spec_source,
            plan_store,
            observer,
            agent_runtime,
            workspace_manager,
            stop_after=3,
        )
        reconciler.run()

        cycle_calls = observer.calls_for("cycle_started")
        assert len(cycle_calls) == 3
        assert cycle_calls[0]["cycle"] == 1
        assert cycle_calls[1]["cycle"] == 2
        assert cycle_calls[2]["cycle"] == 3

    def test_emits_reconciler_halted_on_stop(
        self,
        spec_source: AutoStopSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        reconciler = _make_reconciler(
            spec_source,
            plan_store,
            observer,
            agent_runtime,
            workspace_manager,
            stop_after=2,
        )
        reconciler.run()

        halted_calls = observer.calls_for("reconciler_halted")
        assert len(halted_calls) == 1
        assert halted_calls[0]["reason"] == HaltReason.SHUTDOWN
        assert halted_calls[0]["total_cycles"] == 2

    def test_reconciler_halted_after_last_cycle(
        self,
        spec_source: AutoStopSpecSource,
        plan_store: FakePlanStore,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        reconciler = _make_reconciler(
            spec_source, plan_store, observer, agent_runtime, workspace_manager
        )
        reconciler.run()

        method_order = [c.method for c in observer.calls]
        last_cycle_completed = (
            len(method_order) - 1 - method_order[::-1].index("cycle_completed")
        )
        halted_idx = method_order.index("reconciler_halted")
        assert halted_idx > last_cycle_completed

    def test_idempotent_cycle_with_synced_specs(
        self,
        spec_source: AutoStopSpecSource,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        plan = Plan()
        sp = plan.add_spec("auth.spec.md", "abc123")
        sp.status = SpecPlanStatus.SYNCED
        plan_store = FakePlanStore(plan)

        spec_source.add_spec("auth.spec.md", "abc123")

        reconciler = _make_reconciler(
            spec_source,
            plan_store,
            observer,
            agent_runtime,
            workspace_manager,
            stop_after=2,
        )
        reconciler.run()

        assert observer.calls_for("spec_divergence_detected") == []
        assert observer.calls_for("decomposition_started") == []
        assert observer.calls_for("task_dispatched") == []

    def test_excludes_superseded_from_spec_count(
        self,
        spec_source: AutoStopSpecSource,
        observer: FakeObserver,
        agent_runtime: FakeAgentRuntime,
        workspace_manager: FakeWorkspaceManager,
    ) -> None:
        plan = Plan()
        sp1 = plan.add_spec("auth.spec.md", "old_sha")
        sp1.superseded = True
        plan.add_spec("auth.spec.md", "new_sha")
        plan_store = FakePlanStore(plan)

        spec_source.add_spec("auth.spec.md", "new_sha")

        reconciler = _make_reconciler(
            spec_source, plan_store, observer, agent_runtime, workspace_manager
        )
        reconciler.run()

        started_calls = observer.calls_for("reconciler_started")
        assert started_calls[0]["spec_count"] == 1
