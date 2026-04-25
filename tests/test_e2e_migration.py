"""E2E migration + reconciliation cycle tests.

Simulates scenarios where the orchestrator starts with pre-existing tasks
(as from a migration) and runs through multiple cycles. Covers the full
lifecycle including drift detection, phase orphan reset, worker crashes,
and complete implement-verify-merge pipelines.

Uses InMemoryStateStore + InMemoryRuntime fakes. No mocks.
"""

from __future__ import annotations

from pathlib import Path

from hyperloop.compose import PromptComposer, load_templates_from_dir
from hyperloop.domain.model import (
    Phase,
    PhaseStep,
    Process,
    StepOutcome,
    StepResult,
    Task,
    TaskStatus,
    Verdict,
    WorkerPollStatus,
    WorkerResult,
)
from hyperloop.loop import Orchestrator
from tests.fakes.channel import FakeChannelPort
from tests.fakes.probe import RecordingProbe
from tests.fakes.runtime import InMemoryRuntime
from tests.fakes.spec_source import FakeSpecSource
from tests.fakes.state import InMemoryStateStore
from tests.fakes.step_executor import FakeStepExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS_RESULT = WorkerResult(verdict=Verdict.PASS, detail="All tests pass")
FAIL_RESULT = WorkerResult(verdict=Verdict.FAIL, detail="Tests failed")

DEFAULT_PROCESS = Process(
    name="default",
    phases={
        "implement": PhaseStep(run="agent implementer", on_pass="verify", on_fail="implement"),
        "verify": PhaseStep(run="agent verifier", on_pass="done", on_fail="implement"),
    },
)

MERGE_PROCESS = Process(
    name="merge-process",
    phases={
        "implement": PhaseStep(run="agent implementer", on_pass="verify", on_fail="implement"),
        "verify": PhaseStep(run="agent verifier", on_pass="merge", on_fail="implement"),
        "merge": PhaseStep(run="action merge", on_pass="done", on_fail="implement"),
    },
)

BASE_DIR = Path(__file__).parent.parent / "base"


def _task(
    id: str = "task-001",
    status: TaskStatus = TaskStatus.NOT_STARTED,
    deps: tuple[str, ...] = (),
    round: int = 0,
    phase: Phase | None = None,
    branch: str | None = None,
    pr: str | None = None,
    spec_ref: str | None = None,
) -> Task:
    return Task(
        id=id,
        title=f"Task {id}",
        spec_ref=spec_ref or f"specs/{id}.md",
        status=status,
        phase=phase,
        deps=deps,
        round=round,
        branch=branch,
        pr=pr,
    )


def _make_orchestrator(
    state: InMemoryStateStore,
    runtime: InMemoryRuntime,
    process: Process = DEFAULT_PROCESS,
    max_workers: int = 6,
    max_task_rounds: int = 50,
    step_executor: FakeStepExecutor | None = None,
    channel: FakeChannelPort | None = None,
    composer: PromptComposer | None = None,
    poll_interval: float = 0,
    probe: RecordingProbe | None = None,
    spec_source: FakeSpecSource | None = None,
) -> Orchestrator:
    return Orchestrator(
        state=state,
        runtime=runtime,
        process=process,
        max_workers=max_workers,
        max_task_rounds=max_task_rounds,
        step_executor=step_executor,
        channel=channel,
        spec_source=spec_source,
        composer=composer,
        poll_interval=poll_interval,
        probe=probe or RecordingProbe(),
    )


# ---------------------------------------------------------------------------
# Test 1: Full migration cycle
# ---------------------------------------------------------------------------


class TestFullMigrationCycle:
    """Orchestrator starts with pre-existing migrated tasks and walks them
    through the pipeline over multiple cycles."""

    def test_full_migration_cycle(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()

        # 3 completed tasks (old work, already done)
        state.add_task(_task(id="task-done-1", status=TaskStatus.COMPLETED))
        state.add_task(_task(id="task-done-2", status=TaskStatus.COMPLETED))
        state.add_task(_task(id="task-done-3", status=TaskStatus.COMPLETED))
        # Seed spec files so deleted-spec detection does not interfere
        state.set_file("specs/task-done-1.md", "done spec 1")
        state.set_file("specs/task-done-2.md", "done spec 2")
        state.set_file("specs/task-done-3.md", "done spec 3")

        # 2 not-started tasks
        state.add_task(_task(id="task-ns-1", status=TaskStatus.NOT_STARTED))
        state.add_task(_task(id="task-ns-2", status=TaskStatus.NOT_STARTED))
        state.set_file("specs/task-ns-1.md", "ns spec 1")
        state.set_file("specs/task-ns-2.md", "ns spec 2")

        # 1 in-progress task at phase "implement" (mid-flight from migration)
        state.add_task(
            _task(
                id="task-ip-1",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implement"),
                branch="hyperloop/task-ip-1",
            )
        )
        state.set_file("specs/task-ip-1.md", "ip spec 1")

        orch = _make_orchestrator(state, runtime, probe=probe)

        # Cycle 1: in-progress task should get a worker spawned,
        # not-started tasks should also get workers spawned
        orch.run_cycle(cycle_num=1)

        # Verify in-progress task still has a worker
        assert state.get_task("task-ip-1").status == TaskStatus.IN_PROGRESS
        assert "task-ip-1" in runtime.handles

        # Verify not-started tasks are now in-progress
        assert state.get_task("task-ns-1").status == TaskStatus.IN_PROGRESS
        assert state.get_task("task-ns-2").status == TaskStatus.IN_PROGRESS

        # Verify completed tasks are untouched
        assert state.get_task("task-done-1").status == TaskStatus.COMPLETED
        assert state.get_task("task-done-2").status == TaskStatus.COMPLETED
        assert state.get_task("task-done-3").status == TaskStatus.COMPLETED

        # Simulate all workers completing with PASS
        for tid in ["task-ip-1", "task-ns-1", "task-ns-2"]:
            runtime.set_poll_status(tid, WorkerPollStatus.DONE)
            runtime.set_result(tid, PASS_RESULT)

        # Cycle 2: reap implementers, advance to verify
        orch.run_cycle(cycle_num=2)

        for tid in ["task-ip-1", "task-ns-1", "task-ns-2"]:
            task = state.get_task(tid)
            assert task.status == TaskStatus.IN_PROGRESS
            assert task.phase == Phase("verify")

        # Simulate verifiers completing with PASS
        for tid in ["task-ip-1", "task-ns-1", "task-ns-2"]:
            runtime.set_poll_status(tid, WorkerPollStatus.DONE)
            runtime.set_result(tid, PASS_RESULT)

        # Cycle 3: reap verifiers, on_pass="done" -> COMPLETED
        orch.run_cycle(cycle_num=3)

        for tid in ["task-ip-1", "task-ns-1", "task-ns-2"]:
            task = state.get_task(tid)
            assert task.status == TaskStatus.COMPLETED

        # All 6 tasks should now be COMPLETED
        world = state.get_world()
        assert all(t.status == TaskStatus.COMPLETED for t in world.tasks.values())


# ---------------------------------------------------------------------------
# Test 2: Drift detection triggers intake after migration
# ---------------------------------------------------------------------------


class TestDriftDetectionTriggersIntakeAfterMigration:
    """Completed tasks pinned to an old SHA trigger freshness drift
    when a SpecSource reports a different current SHA."""

    def test_drift_detection_triggers_intake_after_migration(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        # Completed task pinned to old SHA
        state.add_task(
            Task(
                id="task-old-1",
                title="Old task",
                spec_ref="specs/auth.md@oldsha",
                status=TaskStatus.COMPLETED,
                phase=None,
                deps=(),
                round=1,
                branch="hyperloop/task-old-1",
                pr=None,
            )
        )
        state.set_file("specs/auth.md", "Auth spec content")

        # In-progress task pinned to old SHA
        state.add_task(
            Task(
                id="task-old-2",
                title="Active old task",
                spec_ref="specs/auth.md@oldsha",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implement"),
                deps=(),
                round=0,
                branch="hyperloop/task-old-2",
                pr=None,
            )
        )

        spec_source = FakeSpecSource()
        spec_source.add_spec("specs/auth.md", "Auth spec content")
        spec_source.set_version("newsha")

        orch = _make_orchestrator(
            state, runtime, composer=composer, probe=probe, spec_source=spec_source
        )
        orch.run_cycle(cycle_num=1)

        # Drift should be detected
        drift_calls = probe.of_method("drift_detected")
        freshness_drifts = [c for c in drift_calls if c["drift_type"] == "freshness"]
        assert len(freshness_drifts) >= 1
        assert any("auth" in str(c["spec_path"]) for c in freshness_drifts)

        # PM intake should have been triggered (runtime.serial_runs has a PM call)
        pm_runs = [r for r in runtime.serial_runs if r.role == "pm"]
        assert len(pm_runs) >= 1


# ---------------------------------------------------------------------------
# Test 3: Phase orphan reset on migration
# ---------------------------------------------------------------------------


class TestPhaseOrphanResetOnMigration:
    """A task at a phase not in the current phase map is reset to the
    first phase, and a task_reset probe event is emitted."""

    def test_phase_orphan_reset_on_migration(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()

        # Task at phase "old-phase" which does not exist in DEFAULT_PROCESS
        state.add_task(
            _task(
                id="task-orphan",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("old-phase"),
                round=3,
                branch="hyperloop/task-orphan",
            )
        )
        state.set_file("specs/task-orphan.md", "orphan spec")

        orch = _make_orchestrator(state, runtime, probe=probe)
        orch.run_cycle(cycle_num=1)

        task = state.get_task("task-orphan")
        # Should be reset to first phase ("implement")
        assert task.phase == Phase("implement")
        assert task.status == TaskStatus.IN_PROGRESS

        # task_reset probe event should be emitted
        reset_calls = probe.of_method("task_reset")
        assert len(reset_calls) >= 1
        orphan_resets = [c for c in reset_calls if c["task_id"] == "task-orphan"]
        assert len(orphan_resets) == 1
        assert "process changed" in str(orphan_resets[0]["reason"]).lower()


# ---------------------------------------------------------------------------
# Test 4: Worker crash during cycle
# ---------------------------------------------------------------------------


class TestWorkerCrashDuringCycle:
    """When a worker's poll returns FAILED (not DONE), the crash is detected,
    probe emits worker_crash_detected, and channel.worker_crashed() is called."""

    def test_worker_crash_during_cycle(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        channel = FakeChannelPort()
        probe = RecordingProbe()

        state.add_task(_task(id="task-crash"))
        state.set_file("specs/task-crash.md", "crash spec")

        orch = _make_orchestrator(state, runtime, channel=channel, probe=probe)

        # Cycle 1: spawn implementer
        orch.run_cycle(cycle_num=1)
        assert state.get_task("task-crash").status == TaskStatus.IN_PROGRESS

        # Worker crashes: poll returns FAILED
        runtime.set_poll_status("task-crash", WorkerPollStatus.FAILED)
        runtime.set_result(
            "task-crash",
            WorkerResult(verdict=Verdict.FAIL, detail="Agent future missing or failed"),
        )

        # Cycle 2: reap crash
        orch.run_cycle(cycle_num=2)

        # Verify worker_crash_detected probe is emitted
        crash_calls = probe.of_method("worker_crash_detected")
        assert len(crash_calls) >= 1
        crash_for_task = [c for c in crash_calls if c["task_id"] == "task-crash"]
        assert len(crash_for_task) == 1
        assert crash_for_task[0]["role"] == "implementer"

        # Verify channel.worker_crashed() was called
        assert len(channel.worker_crashed_calls) == 1
        task_id, role, _branch = channel.worker_crashed_calls[0]
        assert task_id == "task-crash"
        assert role == "implementer"


# ---------------------------------------------------------------------------
# Test 5: Full implement -> verify -> merge cycle
# ---------------------------------------------------------------------------


class TestFullImplementVerifyMergeCycle:
    """A task walks through the complete lifecycle:
    spawn implementer -> PASS -> advance to verify ->
    spawn verifier -> PASS -> advance to merge ->
    action merge executes -> ADVANCE -> task COMPLETED."""

    def test_full_implement_verify_merge_cycle(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        step_exec = FakeStepExecutor()
        probe = RecordingProbe()

        # Configure merge action to return ADVANCE
        step_exec.set_default(StepResult(outcome=StepOutcome.ADVANCE, detail="merged"))

        state.add_task(
            _task(
                id="task-full",
                status=TaskStatus.NOT_STARTED,
                branch="hyperloop/task-full",
            )
        )
        state.set_file("specs/task-full.md", "full lifecycle spec")

        orch = _make_orchestrator(
            state,
            runtime,
            process=MERGE_PROCESS,
            step_executor=step_exec,
            probe=probe,
        )

        # Cycle 1: spawn implementer
        orch.run_cycle(cycle_num=1)
        task = state.get_task("task-full")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("implement")

        # Implementer passes
        runtime.set_poll_status("task-full", WorkerPollStatus.DONE)
        runtime.set_result("task-full", PASS_RESULT)

        # Cycle 2: reap implementer, advance to verify, spawn verifier
        orch.run_cycle(cycle_num=2)
        task = state.get_task("task-full")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("verify")

        # Verifier passes
        runtime.set_poll_status("task-full", WorkerPollStatus.DONE)
        runtime.set_result("task-full", PASS_RESULT)

        # Cycle 3: reap verifier, advance to merge phase
        orch.run_cycle(cycle_num=3)
        task = state.get_task("task-full")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("merge")

        # Cycle 4: action step "merge" executes -> ADVANCE -> COMPLETED
        orch.run_cycle(cycle_num=4)
        task = state.get_task("task-full")
        assert task.status == TaskStatus.COMPLETED

        # Verify the merge step was executed
        assert len(step_exec.executed) >= 1
        merge_executions = [e for e in step_exec.executed if e[1] == "merge"]
        assert len(merge_executions) == 1
        assert merge_executions[0][0] == "task-full"

        # Verify probe recorded the full lifecycle
        spawned = probe.of_method("worker_spawned")
        assert len(spawned) >= 2  # implementer + verifier

        step_calls = probe.of_method("step_executed")
        merge_steps = [c for c in step_calls if c["step_name"] == "merge"]
        assert len(merge_steps) >= 1
