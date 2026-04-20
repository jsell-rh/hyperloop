"""Tests for the domain model — value objects, entities, and pipeline primitives."""

from hyperloop.domain.model import (
    ActionStep,
    AdvanceTask,
    AgentStep,
    GateStep,
    Halt,
    LoopStep,
    Phase,
    PipelineStep,
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
        assert TaskStatus.COMPLETE.value == "complete"
        assert TaskStatus.FAILED.value == "failed"

    def test_all_members(self):
        members = {s.name for s in TaskStatus}
        assert members == {"NOT_STARTED", "IN_PROGRESS", "COMPLETE", "FAILED"}


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


class TestPipelineStep:
    def test_agent_step(self):
        step = AgentStep(agent="implementer", on_pass=None, on_fail=None)
        assert step.agent == "implementer"
        assert isinstance(step, AgentStep)

    def test_agent_step_with_routing(self):
        step = AgentStep(agent="verifier", on_pass="merge", on_fail="implement")
        assert step.on_pass == "merge"
        assert step.on_fail == "implement"

    def test_gate_step(self):
        step = GateStep(gate="human-pr-approval")
        assert step.gate == "human-pr-approval"
        assert isinstance(step, GateStep)

    def test_action_step(self):
        step = ActionStep(action="merge-pr")
        assert step.action == "merge-pr"
        assert isinstance(step, ActionStep)

    def test_loop_step_with_nested_agents(self):
        impl = AgentStep(agent="implementer", on_pass=None, on_fail=None)
        verify = AgentStep(agent="verifier", on_pass=None, on_fail=None)
        loop = LoopStep(steps=(impl, verify))
        assert len(loop.steps) == 2
        assert isinstance(loop.steps[0], AgentStep)
        assert isinstance(loop.steps[1], AgentStep)

    def test_pipeline_step_union_isinstance(self):
        """Verify that all pipeline step types satisfy the PipelineStep union."""
        steps: list[PipelineStep] = [
            AgentStep(agent="implementer", on_pass=None, on_fail=None),
            GateStep(gate="approval"),
            LoopStep(steps=()),
            ActionStep(action="merge-pr"),
        ]
        for step in steps:
            assert isinstance(step, AgentStep | GateStep | LoopStep | ActionStep)


class TestProcess:
    def test_creation(self):
        process = Process(
            name="default",
            pipeline=(
                LoopStep(
                    steps=(
                        AgentStep(agent="implementer", on_pass=None, on_fail=None),
                        AgentStep(agent="verifier", on_pass=None, on_fail=None),
                    )
                ),
                ActionStep(action="merge-pr"),
            ),
        )
        assert process.name == "default"
        assert len(process.pipeline) == 2
        assert isinstance(process.pipeline[0], LoopStep)
        assert isinstance(process.pipeline[1], ActionStep)

    def test_nested_loop_structure(self):
        """Process with a loop containing agent steps matches the spec example."""
        inner_loop = LoopStep(
            steps=(
                AgentStep(agent="implementer", on_pass=None, on_fail=None),
                AgentStep(agent="verifier", on_pass=None, on_fail=None),
            )
        )
        process = Process(
            name="complex",
            pipeline=(inner_loop, ActionStep(action="merge-pr")),
        )
        loop = process.pipeline[0]
        assert isinstance(loop, LoopStep)
        assert loop.steps[0] == AgentStep(agent="implementer", on_pass=None, on_fail=None)
        assert loop.steps[1] == AgentStep(agent="verifier", on_pass=None, on_fail=None)


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
            to_status=TaskStatus.COMPLETE,
            to_phase=None,
        )
        assert action.to_phase is None

    def test_halt(self):
        action = Halt(reason="max_rounds exceeded")
        assert action.reason == "max_rounds exceeded"
