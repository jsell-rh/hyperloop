"""Tests for the domain model -- value objects, entities, and process definition."""

from hyperloop.domain.model import (
    AdvanceTask,
    Halt,
    Phase,
    PhaseStep,
    Process,
    ReapWorker,
    SpawnWorker,
    Task,
    TaskStatus,
    Verdict,
    WorkerHandle,
    WorkerResult,
    WorkerState,
    World,
)


class TestTaskStatus:
    def test_enum_values(self):
        assert TaskStatus.NOT_STARTED.value == "not_started"
        assert TaskStatus.IN_PROGRESS.value == "in_progress"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"

    def test_all_members(self):
        members = {s.name for s in TaskStatus}
        assert members == {"NOT_STARTED", "IN_PROGRESS", "COMPLETED", "FAILED"}


class TestVerdict:
    def test_enum_values(self):
        assert Verdict.PASS.value == "pass"
        assert Verdict.FAIL.value == "fail"

    def test_all_members(self):
        members = {v.name for v in Verdict}
        assert members == {"PASS", "FAIL"}


class TestTask:
    def test_creation_with_all_fields(self):
        task = Task(
            id="task-027",
            title="Implement Places DB persistent storage",
            spec_ref="specs/persistence.md",
            status=TaskStatus.NOT_STARTED,
            phase=Phase("implement"),
            deps=("task-004",),
            round=0,
            branch="hyperloop/task-027",
            pr="https://github.com/org/repo/pull/42",
        )
        assert task.id == "task-027"
        assert task.title == "Implement Places DB persistent storage"
        assert task.spec_ref == "specs/persistence.md"
        assert task.status == TaskStatus.NOT_STARTED
        assert task.phase == Phase("implement")
        assert task.deps == ("task-004",)
        assert task.round == 0
        assert task.branch == "hyperloop/task-027"
        assert task.pr == "https://github.com/org/repo/pull/42"

    def test_creation_with_none_optionals(self):
        task = Task(
            id="task-001",
            title="A task",
            spec_ref="specs/foo.md",
            status=TaskStatus.NOT_STARTED,
            phase=None,
            deps=(),
            round=0,
            branch=None,
            pr=None,
        )
        assert task.phase is None
        assert task.branch is None
        assert task.pr is None


class TestTaskImmutability:
    def test_frozen_task_rejects_mutation(self):
        task = Task(
            id="task-001",
            title="A task",
            spec_ref="specs/foo.md",
            status=TaskStatus.NOT_STARTED,
            phase=None,
            deps=(),
            round=0,
            branch=None,
            pr=None,
        )
        import pytest

        with pytest.raises(AttributeError):
            task.status = TaskStatus.IN_PROGRESS  # type: ignore[misc]

    def test_deps_is_tuple_not_list(self):
        task = Task(
            id="task-001",
            title="A task",
            spec_ref="specs/foo.md",
            status=TaskStatus.NOT_STARTED,
            phase=None,
            deps=("task-002",),
            round=0,
            branch=None,
            pr=None,
        )
        assert isinstance(task.deps, tuple)


class TestWorkerResult:
    def test_creation(self):
        result = WorkerResult(
            verdict=Verdict.PASS,
            detail="All tests pass, check scripts pass",
        )
        assert result.verdict == Verdict.PASS
        assert result.detail == "All tests pass, check scripts pass"

    def test_fail_verdict(self):
        result = WorkerResult(
            verdict=Verdict.FAIL,
            detail="3 test failures in module X",
        )
        assert result.verdict == Verdict.FAIL


class TestWorkerHandle:
    def test_creation(self):
        handle = WorkerHandle(
            task_id="task-027",
            role="implementer",
            agent_id="agent-abc123",
            session_id="session-xyz",
        )
        assert handle.task_id == "task-027"
        assert handle.role == "implementer"
        assert handle.agent_id == "agent-abc123"
        assert handle.session_id == "session-xyz"

    def test_creation_without_session(self):
        handle = WorkerHandle(
            task_id="task-027",
            role="implementer",
            agent_id="agent-abc123",
            session_id=None,
        )
        assert handle.session_id is None


class TestProcess:
    def test_creation_with_phases(self):
        process = Process(
            name="default",
            phases={
                "implement": PhaseStep(
                    run="agent implementer", on_pass="verify", on_fail="implement"
                ),
                "verify": PhaseStep(run="agent verifier", on_pass="merge", on_fail="implement"),
                "merge": PhaseStep(run="action merge", on_pass="done", on_fail="implement"),
            },
        )
        assert process.name == "default"
        assert len(process.phases) == 3

    def test_empty_phases(self):
        process = Process(name="empty")
        assert process.phases == {}


class TestWorkerState:
    def test_creation(self):
        ws = WorkerState(task_id="task-027", role="implementer", status="running")
        assert ws.task_id == "task-027"
        assert ws.role == "implementer"
        assert ws.status == "running"


class TestWorld:
    def test_creation(self):
        task = Task(
            id="task-001",
            title="Test task",
            spec_ref="specs/test.md",
            status=TaskStatus.NOT_STARTED,
            phase=None,
            deps=(),
            round=0,
            branch=None,
            pr=None,
        )
        worker = WorkerState(task_id="task-001", role="implementer", status="running")
        world = World(
            tasks={"task-001": task},
            workers={"worker-1": worker},
            epoch="abc123",
        )
        assert world.tasks["task-001"].id == "task-001"
        assert world.workers["worker-1"].status == "running"
        assert world.epoch == "abc123"


class TestActions:
    def test_spawn_worker(self):
        action = SpawnWorker(task_id="task-001", role="implementer")
        assert action.task_id == "task-001"
        assert action.role == "implementer"

    def test_reap_worker(self):
        action = ReapWorker(task_id="task-001")
        assert action.task_id == "task-001"

    def test_advance_task(self):
        action = AdvanceTask(
            task_id="task-001",
            to_status=TaskStatus.IN_PROGRESS,
            to_phase=Phase("verify"),
        )
        assert action.task_id == "task-001"
        assert action.to_status == TaskStatus.IN_PROGRESS
        assert action.to_phase == Phase("verify")

    def test_advance_task_no_phase(self):
        action = AdvanceTask(
            task_id="task-001",
            to_status=TaskStatus.COMPLETED,
            to_phase=None,
        )
        assert action.to_phase is None

    def test_halt(self):
        action = Halt(reason="max_rounds exceeded")
        assert action.reason == "max_rounds exceeded"
