from datetime import datetime, timezone

import pytest

from hyperloop.reconciliation.models import (
    EventType,
    Plan,
    SpecPlan,
    SpecPlanStatus,
    Task,
    TaskStatus,
)
from hyperloop.reconciliation.models.agent_handle import AgentHandle


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TestPlanStructure:
    def test_new_plan_is_empty(self) -> None:
        plan = Plan()
        assert plan.spec_plans == []
        assert plan.events == []

    def test_plan_level_events(self) -> None:
        plan = Plan()
        now = _utc_now()
        plan.record_event(
            reason="ReconcilerStarted",
            message="Reconciler started",
            event_type=EventType.NORMAL,
            timestamp=now,
        )
        assert len(plan.events) == 1
        assert plan.events[0].reason == "ReconcilerStarted"

    def test_plan_level_event_aggregation(self) -> None:
        plan = Plan()
        t1 = _utc_now()
        plan.record_event(
            reason="ReconcilerStarted",
            message="Started",
            event_type=EventType.NORMAL,
            timestamp=t1,
        )
        t2 = _utc_now()
        plan.record_event(
            reason="ReconcilerStarted",
            message="Started again",
            event_type=EventType.NORMAL,
            timestamp=t2,
        )
        assert len(plan.events) == 1
        assert plan.events[0].count == 2
        assert plan.events[0].first_timestamp == t1
        assert plan.events[0].last_timestamp == t2


class TestSpecPlan:
    def test_new_spec_plan_defaults(self) -> None:
        sp = SpecPlan(path="auth.spec.md", blob_sha="abc123")
        assert sp.status == SpecPlanStatus.OUT_OF_SYNC
        assert sp.superseded is False
        assert sp.reconciliation_attempts == 0
        assert sp.has_redecomposed is False
        assert sp.tasks == []
        assert sp.events == []

    def test_identity_is_path_plus_sha(self) -> None:
        sp1 = SpecPlan(path="auth.spec.md", blob_sha="abc123")
        sp2 = SpecPlan(path="auth.spec.md", blob_sha="def456")
        assert sp1 != sp2


class TestIdempotentSpecAddition:
    def test_add_spec_creates_spec_plan(self) -> None:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        assert len(plan.spec_plans) == 1
        assert plan.spec_plans[0].path == "auth.spec.md"
        assert plan.spec_plans[0].blob_sha == "abc123"
        assert plan.spec_plans[0].status == SpecPlanStatus.OUT_OF_SYNC

    def test_add_same_spec_is_idempotent(self) -> None:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        plan.add_spec("auth.spec.md", "abc123")
        assert len(plan.spec_plans) == 1

    def test_add_new_sha_supersedes_old(self) -> None:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        plan.add_spec("auth.spec.md", "def456")

        old = [sp for sp in plan.spec_plans if sp.blob_sha == "abc123"]
        new = [sp for sp in plan.spec_plans if sp.blob_sha == "def456"]

        assert len(old) == 1
        assert old[0].superseded is True
        assert len(new) == 1
        assert new[0].superseded is False
        assert new[0].status == SpecPlanStatus.OUT_OF_SYNC

    def test_multiple_old_shas_all_superseded(self) -> None:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        plan.add_spec("auth.spec.md", "bbb222")
        plan.add_spec("auth.spec.md", "def456")

        superseded = [sp for sp in plan.spec_plans if sp.superseded]
        active = [sp for sp in plan.spec_plans if not sp.superseded]

        assert len(superseded) == 2
        assert len(active) == 1
        assert active[0].blob_sha == "def456"

    def test_add_spec_with_reconciling_status_supersedes(self) -> None:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        plan.spec_plans[0].status = SpecPlanStatus.RECONCILING
        plan.add_spec("auth.spec.md", "def456")

        old = [sp for sp in plan.spec_plans if sp.blob_sha == "abc123"][0]
        assert old.superseded is True


class TestTaskAddition:
    def test_adding_tasks_transitions_to_reconciling(self) -> None:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        sp = plan.spec_plans[0]
        assert sp.status == SpecPlanStatus.OUT_OF_SYNC

        task_id = plan.next_task_id()
        plan.add_tasks(
            sp,
            [
                Task(
                    id=task_id,
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    name="Implement login",
                    description="Build login endpoint",
                ),
            ],
        )
        assert sp.status == SpecPlanStatus.RECONCILING

    def test_tasks_reference_parent_spec(self) -> None:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        sp = plan.spec_plans[0]

        task_id = plan.next_task_id()
        plan.add_tasks(
            sp,
            [
                Task(
                    id=task_id,
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    name="Task 1",
                    description="Do something",
                ),
            ],
        )
        assert sp.tasks[0].spec_path == "auth.spec.md"
        assert sp.tasks[0].spec_blob_sha == "abc123"


class TestMonotonicTaskIds:
    def test_first_id_is_one(self) -> None:
        plan = Plan()
        assert plan.next_task_id() == 1

    def test_ids_increment(self) -> None:
        plan = Plan()
        assert plan.next_task_id() == 1
        assert plan.next_task_id() == 2
        assert plan.next_task_id() == 3

    def test_ids_are_globally_unique_across_specs(self) -> None:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        plan.add_spec("users.spec.md", "xyz789")
        sp_a = plan.spec_plans[0]
        sp_b = plan.spec_plans[1]

        id1 = plan.next_task_id()
        id2 = plan.next_task_id()
        plan.add_tasks(
            sp_a,
            [
                Task(
                    id=id1,
                    spec_path=sp_a.path,
                    spec_blob_sha=sp_a.blob_sha,
                    name="T1",
                    description="D1",
                ),
                Task(
                    id=id2,
                    spec_path=sp_a.path,
                    spec_blob_sha=sp_a.blob_sha,
                    name="T2",
                    description="D2",
                ),
            ],
        )

        id3 = plan.next_task_id()
        id4 = plan.next_task_id()
        plan.add_tasks(
            sp_b,
            [
                Task(
                    id=id3,
                    spec_path=sp_b.path,
                    spec_blob_sha=sp_b.blob_sha,
                    name="T3",
                    description="D3",
                ),
                Task(
                    id=id4,
                    spec_path=sp_b.path,
                    spec_blob_sha=sp_b.blob_sha,
                    name="T4",
                    description="D4",
                ),
            ],
        )

        assert plan.next_task_id() == 5

        all_ids = [t.id for sp in plan.spec_plans for t in sp.tasks]
        assert all_ids == [1, 2, 3, 4]
        assert len(set(all_ids)) == len(all_ids)


class TestUnblockedTaskSelection:
    def _build_plan_with_tasks(self) -> tuple[Plan, SpecPlan]:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        sp = plan.spec_plans[0]
        id1 = plan.next_task_id()
        id2 = plan.next_task_id()
        id3 = plan.next_task_id()
        plan.add_tasks(
            sp,
            [
                Task(
                    id=id1,
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    name="T1",
                    description="D1",
                ),
                Task(
                    id=id2,
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    name="T2",
                    description="D2",
                ),
                Task(
                    id=id3,
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    name="T3",
                    description="D3",
                    depends_on=[id1, id2],
                ),
            ],
        )
        return plan, sp

    def test_all_independent_tasks_are_unblocked(self) -> None:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        sp = plan.spec_plans[0]
        ids = [plan.next_task_id() for _ in range(3)]
        plan.add_tasks(
            sp,
            [
                Task(
                    id=ids[0],
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    name="T1",
                    description="D1",
                ),
                Task(
                    id=ids[1],
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    name="T2",
                    description="D2",
                ),
                Task(
                    id=ids[2],
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    name="T3",
                    description="D3",
                ),
            ],
        )
        unblocked = plan.get_unblocked_tasks()
        assert len(unblocked) == 3

    def test_satisfied_dependencies_unblock(self) -> None:
        plan, sp = self._build_plan_with_tasks()
        sp.tasks[0].status = TaskStatus.COMPLETE
        sp.tasks[1].status = TaskStatus.COMPLETE

        unblocked = plan.get_unblocked_tasks()
        unblocked_ids = {t.id for t in unblocked}
        assert 3 in unblocked_ids

    def test_unsatisfied_dependencies_block(self) -> None:
        plan, sp = self._build_plan_with_tasks()
        sp.tasks[0].status = TaskStatus.COMPLETE
        sp.tasks[1].status = TaskStatus.IN_PROGRESS

        unblocked = plan.get_unblocked_tasks()
        unblocked_ids = {t.id for t in unblocked}
        assert 3 not in unblocked_ids

    def test_superseded_spec_tasks_excluded(self) -> None:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        sp = plan.spec_plans[0]
        task_id = plan.next_task_id()
        plan.add_tasks(
            sp,
            [
                Task(
                    id=task_id,
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    name="T1",
                    description="D1",
                )
            ],
        )
        sp.superseded = True

        unblocked = plan.get_unblocked_tasks()
        assert len(unblocked) == 0

    def test_cross_spec_dependency(self) -> None:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        plan.add_spec("users.spec.md", "xyz789")
        sp_a = plan.spec_plans[0]
        sp_b = plan.spec_plans[1]

        id_a = plan.next_task_id()
        plan.add_tasks(
            sp_a,
            [
                Task(
                    id=id_a,
                    spec_path=sp_a.path,
                    spec_blob_sha=sp_a.blob_sha,
                    name="T1",
                    description="D1",
                )
            ],
        )

        id_b = plan.next_task_id()
        plan.add_tasks(
            sp_b,
            [
                Task(
                    id=id_b,
                    spec_path=sp_b.path,
                    spec_blob_sha=sp_b.blob_sha,
                    name="T2",
                    description="D2",
                    depends_on=[id_a],
                ),
            ],
        )

        # Dependency not satisfied
        unblocked = plan.get_unblocked_tasks()
        assert id_b not in {t.id for t in unblocked}

        # Satisfy the dependency
        sp_a.tasks[0].status = TaskStatus.COMPLETE
        unblocked = plan.get_unblocked_tasks()
        assert id_b in {t.id for t in unblocked}

    def test_only_backlog_tasks_are_eligible(self) -> None:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        sp = plan.spec_plans[0]
        task_id = plan.next_task_id()
        plan.add_tasks(
            sp,
            [
                Task(
                    id=task_id,
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    name="T1",
                    description="D1",
                )
            ],
        )
        sp.tasks[0].status = TaskStatus.IN_PROGRESS

        unblocked = plan.get_unblocked_tasks()
        assert len(unblocked) == 0


class TestEvents:
    def test_event_aggregation_same_reason(self) -> None:
        sp = SpecPlan(path="auth.spec.md", blob_sha="abc123")
        t1 = _utc_now()
        sp.record_event(
            reason="TaskFailed",
            message="timeout",
            event_type=EventType.WARNING,
            timestamp=t1,
        )
        assert len(sp.events) == 1
        assert sp.events[0].count == 1
        assert sp.events[0].first_timestamp == t1

        t2 = _utc_now()
        sp.record_event(
            reason="TaskFailed",
            message="timeout again",
            event_type=EventType.WARNING,
            timestamp=t2,
        )
        assert len(sp.events) == 1
        assert sp.events[0].count == 2
        assert sp.events[0].first_timestamp == t1
        assert sp.events[0].last_timestamp == t2

    def test_different_reasons_create_separate_events(self) -> None:
        sp = SpecPlan(path="auth.spec.md", blob_sha="abc123")
        sp.record_event(
            reason="TaskFailed",
            message="timeout",
            event_type=EventType.WARNING,
            timestamp=_utc_now(),
        )
        sp.record_event(
            reason="MergeConflict",
            message="conflict in auth.py",
            event_type=EventType.WARNING,
            timestamp=_utc_now(),
        )
        assert len(sp.events) == 2
        reasons = {e.reason for e in sp.events}
        assert reasons == {"TaskFailed", "MergeConflict"}

    def test_task_event_aggregation(self) -> None:
        task = Task(
            id=1,
            spec_path="auth.spec.md",
            spec_blob_sha="abc123",
            name="T1",
            description="D1",
        )
        t1 = _utc_now()
        task.record_event(
            reason="TaskFailed",
            message="timeout",
            event_type=EventType.WARNING,
            timestamp=t1,
        )
        t2 = _utc_now()
        task.record_event(
            reason="TaskFailed",
            message="timeout again",
            event_type=EventType.WARNING,
            timestamp=t2,
        )
        assert len(task.events) == 1
        assert task.events[0].count == 2


class TestTaskStatus:
    def test_valid_statuses(self) -> None:
        task = Task(id=1, spec_path="a", spec_blob_sha="b", name="T", description="D")
        for status in TaskStatus:
            task.status = status

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValueError):
            Task(
                id=1,
                spec_path="a",
                spec_blob_sha="b",
                name="T",
                description="D",
                status="invalid",
            )


class TestSpecPlanStatus:
    def test_valid_statuses(self) -> None:
        sp = SpecPlan(path="a", blob_sha="b")
        for status in SpecPlanStatus:
            sp.status = status

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValueError):
            SpecPlan(path="a", blob_sha="b", status="invalid")


class TestSerialization:
    def test_plan_roundtrip(self) -> None:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        plan.add_spec("users.spec.md", "xyz789")
        sp = plan.spec_plans[0]

        id1 = plan.next_task_id()
        id2 = plan.next_task_id()
        plan.add_tasks(
            sp,
            [
                Task(
                    id=id1,
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    name="T1",
                    description="D1",
                ),
                Task(
                    id=id2,
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    name="T2",
                    description="D2",
                    depends_on=[id1],
                ),
            ],
        )
        sp.tasks[0].status = TaskStatus.COMPLETE

        now = _utc_now()
        plan.record_event(
            reason="ReconcilerStarted",
            message="Started",
            event_type=EventType.NORMAL,
            timestamp=now,
        )
        sp.record_event(
            reason="TaskFailed",
            message="timeout",
            event_type=EventType.WARNING,
            timestamp=now,
        )

        json_str = plan.model_dump_json()
        restored = Plan.model_validate_json(json_str)

        assert len(restored.spec_plans) == 2
        assert len(restored.spec_plans[0].tasks) == 2
        assert restored.spec_plans[0].tasks[0].status == TaskStatus.COMPLETE
        assert restored.spec_plans[0].tasks[1].depends_on == [id1]
        assert len(restored.events) == 1
        assert len(restored.spec_plans[0].events) == 1
        assert restored.task_id_counter == plan.task_id_counter

    def test_plan_roundtrip_with_handles(self) -> None:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        sp = plan.spec_plans[0]
        sp.verification_handle = AgentHandle(id="verifier-1")

        task_id = plan.next_task_id()
        plan.add_tasks(
            sp,
            [
                Task(
                    id=task_id,
                    spec_path=sp.path,
                    spec_blob_sha=sp.blob_sha,
                    name="T1",
                    description="D1",
                    agent_handle=AgentHandle(id="agent-1"),
                    status=TaskStatus.IN_PROGRESS,
                ),
            ],
        )

        json_str = plan.model_dump_json()
        restored = Plan.model_validate_json(json_str)

        assert restored.spec_plans[0].verification_handle == AgentHandle(
            id="verifier-1"
        )
        assert restored.spec_plans[0].tasks[0].agent_handle == AgentHandle(id="agent-1")
