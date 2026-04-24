"""Tests for the orchestrator loop -- flat phase map, new ports.

Uses InMemoryStateStore, InMemoryRuntime, FakeStepExecutor, FakeSignalPort,
FakeChannelPort, RecordingProbe fakes. No mocks.
"""

from __future__ import annotations

from pathlib import Path

from hyperloop.compose import PromptComposer, load_templates_from_dir
from hyperloop.domain.model import (
    Phase,
    PhaseStep,
    Process,
    Signal,
    SignalStatus,
    StepOutcome,
    StepResult,
    Task,
    TaskStatus,
    Verdict,
    WorkerResult,
)
from hyperloop.loop import Orchestrator
from tests.fakes.channel import FakeChannelPort
from tests.fakes.pr import FakePRManager
from tests.fakes.probe import RecordingProbe
from tests.fakes.runtime import InMemoryRuntime
from tests.fakes.signal import FakeSignalPort
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

SIGNAL_PROCESS = Process(
    name="signal-process",
    phases={
        "implement": PhaseStep(run="agent implementer", on_pass="verify", on_fail="implement"),
        "verify": PhaseStep(
            run="agent verifier",
            on_pass="await-review",
            on_fail="implement",
        ),
        "await-review": PhaseStep(
            run="signal human-approval",
            on_pass="merge",
            on_fail="implement",
            on_wait="await-review",
        ),
        "merge": PhaseStep(run="action merge", on_pass="done", on_fail="implement"),
    },
)


def _task(
    id: str = "task-001",
    status: TaskStatus = TaskStatus.NOT_STARTED,
    deps: tuple[str, ...] = (),
    round: int = 0,
    phase: Phase | None = None,
    branch: str | None = None,
    pr: str | None = None,
) -> Task:
    return Task(
        id=id,
        title=f"Task {id}",
        spec_ref=f"specs/{id}.md",
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
    signal_port: FakeSignalPort | None = None,
    channel: FakeChannelPort | None = None,
    pr_manager: FakePRManager | None = None,
    composer: PromptComposer | None = None,
    poll_interval: float = 0,
    probe: RecordingProbe | None = None,
    max_action_attempts: int = 3,
) -> Orchestrator:
    return Orchestrator(
        state=state,
        runtime=runtime,
        process=process,
        max_workers=max_workers,
        max_task_rounds=max_task_rounds,
        max_action_attempts=max_action_attempts,
        step_executor=step_executor,
        signal_port=signal_port,
        channel=channel,
        pr=pr_manager,
        composer=composer,
        poll_interval=poll_interval,
        probe=probe or RecordingProbe(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSingleTaskEndToEnd:
    """Task starts not-started, worker spawns, completes through phases."""

    def test_single_task_completes_through_full_pipeline(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime)

        # Cycle 1: spawn implementer
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("implement")

        # Simulate implementer completing with pass
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: reap implementer, advance to verify, spawn verifier
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("verify")

        # Simulate verifier completing with pass
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 3: reap verifier, on_pass="done" -> COMPLETED
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.status == TaskStatus.COMPLETED

    def test_state_store_transitions_are_committed(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime)
        orch.run_cycle()

        assert len(state.committed_messages) > 0


class TestFailedVerificationLoopsBack:
    """Worker fails verification, task loops back, round increments."""

    def test_fail_increments_round_and_restarts(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime)

        # Cycle 1: spawn implementer
        orch.run_cycle()
        assert state.get_task("task-001").phase == Phase("implement")

        # Implementer passes
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: reap implementer, advance to verify
        orch.run_cycle()
        assert state.get_task("task-001").phase == Phase("verify")

        # Verifier fails
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", FAIL_RESULT)

        # Cycle 3: reap verifier, on_fail="implement", round increments
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.round == 1
        assert task.phase == Phase("implement")

    def test_findings_are_stored_on_failure(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime)

        # Cycle 1: spawn implementer
        orch.run_cycle()

        # Implementer passes
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: advance to verify
        orch.run_cycle()

        # Verifier fails
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", FAIL_RESULT)

        # Cycle 3: reap failure, store findings
        orch.run_cycle()
        findings = state.get_findings("task-001")
        assert "Tests failed" in findings


class TestMaxRoundsHalts:
    """Task hits max_task_rounds -> failed, loop halts."""

    def test_max_task_rounds_transitions_to_failed(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(
            _task(
                status=TaskStatus.IN_PROGRESS,
                round=2,
                phase=Phase("implement"),
            )
        )

        orch = _make_orchestrator(state, runtime, max_task_rounds=3)

        # Cycle 1: spawn implementer (round 2, max is 3)
        orch.run_cycle()

        # Implementer passes, advance to verify
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)
        orch.run_cycle()

        # Verifier fails -> round becomes 3 == max_task_rounds
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", FAIL_RESULT)
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.FAILED

    def test_run_loop_halts_on_max_task_rounds(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(round=2))

        orch = _make_orchestrator(state, runtime, max_task_rounds=3)

        # Cycle 1: spawn implementer
        orch.run_cycle()

        # Implementer passes -> verify
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)
        orch.run_cycle()

        # Verifier fails -> round becomes 3 == max_task_rounds -> FAILED
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", FAIL_RESULT)
        reason = orch.run_cycle()

        assert reason is not None
        assert "max_task_rounds" in reason.lower()


class TestMultipleTasksInParallel:
    """Two independent tasks spawn, both complete."""

    def test_two_tasks_spawn_in_parallel(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(id="task-001"))
        state.add_task(_task(id="task-002"))

        orch = _make_orchestrator(state, runtime, max_workers=6)

        # Cycle 1: both tasks should spawn
        orch.run_cycle()
        assert state.get_task("task-001").status == TaskStatus.IN_PROGRESS
        assert state.get_task("task-002").status == TaskStatus.IN_PROGRESS

    def test_both_tasks_complete(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(id="task-001"))
        state.add_task(_task(id="task-002"))

        orch = _make_orchestrator(state, runtime, max_workers=6)

        # Cycle 1: spawn both
        orch.run_cycle()

        # Both implementers pass
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)
        runtime.set_poll_status("task-002", "done")
        runtime.set_result("task-002", PASS_RESULT)

        # Cycle 2: reap both, advance to verify
        orch.run_cycle()
        assert state.get_task("task-001").phase == Phase("verify")
        assert state.get_task("task-002").phase == Phase("verify")

        # Both verifiers pass
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)
        runtime.set_poll_status("task-002", "done")
        runtime.set_result("task-002", PASS_RESULT)

        # Cycle 3: reap verifiers, both complete
        orch.run_cycle()
        assert state.get_task("task-001").status == TaskStatus.COMPLETED
        assert state.get_task("task-002").status == TaskStatus.COMPLETED

    def test_max_workers_limits_parallel_spawns(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(id="task-001"))
        state.add_task(_task(id="task-002"))
        state.add_task(_task(id="task-003"))

        orch = _make_orchestrator(state, runtime, max_workers=2)

        # Cycle 1: only 2 spawn due to max_workers
        orch.run_cycle()
        in_progress = [
            tid
            for tid in ["task-001", "task-002", "task-003"]
            if state.get_task(tid).status == TaskStatus.IN_PROGRESS
        ]
        assert len(in_progress) == 2


class TestDependencyOrdering:
    """task-002 depends on task-001. task-001 completes first."""

    def test_dependent_task_waits_for_dependency(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(id="task-001"))
        state.add_task(_task(id="task-002", deps=("task-001",)))

        orch = _make_orchestrator(state, runtime)

        # Cycle 1: only task-001 spawns
        orch.run_cycle()
        assert state.get_task("task-001").status == TaskStatus.IN_PROGRESS
        assert state.get_task("task-002").status == TaskStatus.NOT_STARTED

    def test_dependent_task_spawns_after_dependency_completes(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(id="task-001"))
        state.add_task(_task(id="task-002", deps=("task-001",)))

        orch = _make_orchestrator(state, runtime)

        # Cycle 1: spawn task-001
        orch.run_cycle()

        # task-001 implementer passes
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: advance to verify, task-002 still not eligible
        orch.run_cycle()
        assert state.get_task("task-001").phase == Phase("verify")
        assert state.get_task("task-002").status == TaskStatus.NOT_STARTED

        # task-001 verifier passes
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 3: task-001 complete, task-002 now eligible
        orch.run_cycle()
        assert state.get_task("task-001").status == TaskStatus.COMPLETED
        assert state.get_task("task-002").status == TaskStatus.IN_PROGRESS


class TestConvergence:
    """All tasks complete, loop halts."""

    def test_run_loop_halts_when_all_complete(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(id="task-001"))

        orch = _make_orchestrator(state, runtime)

        runtime.set_result("task-001", PASS_RESULT)
        runtime.set_poll_status("task-001", "done")

        reason = orch.run_loop(max_cycles=20)
        assert "all tasks complete" in reason.lower()
        assert state.get_task("task-001").status == TaskStatus.COMPLETED

    def test_run_loop_returns_safety_limit_reason(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(id="task-001"))

        orch = _make_orchestrator(state, runtime)
        reason = orch.run_loop(max_cycles=3)
        assert "max_cycles" in reason.lower()

    def test_empty_process_halts_immediately(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(id="task-001", status=TaskStatus.COMPLETED))

        orch = _make_orchestrator(state, runtime)
        reason = orch.run_loop(max_cycles=10)
        assert "all tasks complete" in reason.lower()


class TestRunCycleStepByStep:
    """run_cycle returns halt/None correctly."""

    def test_run_cycle_returns_none_when_not_halted(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime)
        result = orch.run_cycle()
        assert result is None

    def test_run_cycle_returns_reason_when_halted(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(status=TaskStatus.COMPLETED))

        orch = _make_orchestrator(state, runtime)
        result = orch.run_cycle()
        assert result is not None
        assert "all tasks complete" in result.lower()


class TestRecovery:
    """Crash recovery: orphaned workers cancelled, in-progress tasks re-spawned."""

    def test_recover_cancels_orphaned_worker(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implement"),
                branch="hyperloop/task-001",
            )
        )

        runtime.spawn("task-001", "implementer", "", "hyperloop/task-001")

        orch = _make_orchestrator(state, runtime)
        orch.recover()

        assert "task-001" in runtime.cancelled

    def test_recover_respawns_in_progress_task_next_cycle(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implement"),
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(state, runtime)
        orch.recover()

        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        handle = runtime.handles.get("task-001")
        assert handle is not None

    def test_recover_ignores_non_in_progress_tasks(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        state.add_task(_task(id="task-001", status=TaskStatus.NOT_STARTED))
        state.add_task(_task(id="task-002", status=TaskStatus.COMPLETED))
        state.add_task(_task(id="task-003", status=TaskStatus.FAILED))

        orch = _make_orchestrator(state, runtime)
        orch.recover()

        assert "task-001" not in runtime.cancelled
        assert "task-002" not in runtime.cancelled
        assert "task-003" not in runtime.cancelled

    def test_recover_handles_no_orphan(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implement"),
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(state, runtime)
        orch.recover()

        assert "task-001" not in runtime.cancelled

        orch.run_cycle()
        handle = runtime.handles.get("task-001")
        assert handle is not None


class TestStepExecution:
    """Action steps execute via StepExecutor and transition based on outcome."""

    def test_action_advance_completes_task(self) -> None:
        """Action ADVANCE at terminal phase completes the task."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        step_exec = FakeStepExecutor()
        step_exec.set_default(StepResult(outcome=StepOutcome.ADVANCE, detail="merged"))

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge"),
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(
            state,
            runtime,
            process=MERGE_PROCESS,
            step_executor=step_exec,
        )
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.COMPLETED

    def test_action_retry_loops_back(self) -> None:
        """Action RETRY transitions to on_fail phase."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        step_exec = FakeStepExecutor()
        step_exec.set_default(StepResult(outcome=StepOutcome.RETRY, detail="merge conflict"))

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge"),
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(
            state,
            runtime,
            process=MERGE_PROCESS,
            step_executor=step_exec,
        )
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("implement")
        assert task.round == 1

    def test_action_wait_stays_at_phase(self) -> None:
        """Action WAIT keeps the task at current phase."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        step_exec = FakeStepExecutor()
        step_exec.set_default(StepResult(outcome=StepOutcome.WAIT, detail="CI pending"))

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge"),
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(
            state,
            runtime,
            process=MERGE_PROCESS,
            step_executor=step_exec,
        )
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("merge")

    def test_action_advance_stores_pr_url(self) -> None:
        """When StepResult includes pr_url, it is stored on the task."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        step_exec = FakeStepExecutor()
        step_exec.set_default(
            StepResult(
                outcome=StepOutcome.ADVANCE,
                detail="merged",
                pr_url="https://github.com/org/repo/pull/99",
            )
        )

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge"),
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(
            state,
            runtime,
            process=MERGE_PROCESS,
            step_executor=step_exec,
        )
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.pr == "https://github.com/org/repo/pull/99"


class TestSignalStep:
    """Signal steps poll SignalPort and transition accordingly."""

    def test_signal_approved_advances(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        signal = FakeSignalPort()
        signal.set_signal(
            "task-001",
            "human-approval",
            Signal(status=SignalStatus.APPROVED, message="lgtm"),
        )

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("await-review"),
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(state, runtime, process=SIGNAL_PROCESS, signal_port=signal)
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.phase == Phase("merge")

    def test_signal_rejected_retries(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        signal = FakeSignalPort()
        signal.set_signal(
            "task-001",
            "human-approval",
            Signal(status=SignalStatus.REJECTED, message="needs timeout"),
        )

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("await-review"),
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(state, runtime, process=SIGNAL_PROCESS, signal_port=signal)
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.phase == Phase("implement")
        assert task.round == 1

    def test_signal_pending_waits(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        signal = FakeSignalPort()
        # Default is PENDING

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("await-review"),
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(state, runtime, process=SIGNAL_PROCESS, signal_port=signal)
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.phase == Phase("await-review")
        assert task.round == 0

    def test_signal_rejected_stores_finding(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        signal = FakeSignalPort()
        signal.set_signal(
            "task-001",
            "human-approval",
            Signal(status=SignalStatus.REJECTED, message="add timeout handling"),
        )

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("await-review"),
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(state, runtime, process=SIGNAL_PROCESS, signal_port=signal)
        orch.run_cycle()

        findings = state.get_findings("task-001")
        assert "add timeout handling" in findings


class TestWorkerCrash:
    """Worker crash defaults to FAIL + channel notification."""

    def test_worker_crash_defaults_to_fail(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        channel = FakeChannelPort()
        probe = RecordingProbe()

        state.add_task(_task())

        orch = _make_orchestrator(state, runtime, channel=channel, probe=probe)

        # Cycle 1: spawn implementer
        orch.run_cycle()

        # Worker crashes (no verdict)
        runtime.set_poll_status("task-001", "done")
        runtime.set_result(
            "task-001",
            WorkerResult(
                verdict=Verdict.FAIL,
                detail="worker completed without writing verdict",
            ),
        )

        # Cycle 2: reap crash
        orch.run_cycle()

        task = state.get_task("task-001")
        # Should retry (on_fail = implement)
        assert task.phase == Phase("implement")
        assert task.round == 1


class TestDeadlockDetection:
    """Deadlock detection when failed deps block remaining work."""

    def test_deadlock_halts(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        state.add_task(_task(id="task-001", status=TaskStatus.FAILED))
        state.add_task(_task(id="task-002", deps=("task-001",)))

        orch = _make_orchestrator(state, runtime)
        reason = orch.run_cycle()

        assert reason is not None
        assert "deadlock" in reason.lower()


class TestEarlyExitNoTasks:
    """Loop halts immediately when no tasks."""

    def test_empty_world_halts_immediately(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        orch = _make_orchestrator(state, runtime)
        reason = orch.run_loop(max_cycles=100)
        assert "no tasks" in reason.lower()

    def test_empty_world_single_cycle(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        orch = _make_orchestrator(state, runtime)
        reason = orch.run_cycle()
        assert reason is not None
        assert "no tasks" in reason.lower()


class TestProbeIntegration:
    """Probe is invoked during orchestrator lifecycle."""

    def test_cycle_started_fires_each_cycle(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        probe = RecordingProbe()
        orch = _make_orchestrator(state, runtime, probe=probe)

        orch.run_loop(max_cycles=3)
        cycle_calls = probe.of_method("cycle_started")
        assert len(cycle_calls) == 3

    def test_cycle_started_receives_cycle_number(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        probe = RecordingProbe()
        orch = _make_orchestrator(state, runtime, probe=probe)

        orch.run_loop(max_cycles=2)
        cycle_calls = probe.of_method("cycle_started")
        assert cycle_calls[0]["cycle"] == 1
        assert cycle_calls[1]["cycle"] == 2

    def test_orchestrator_halted_fires_on_completion(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        probe = RecordingProbe()
        orch = _make_orchestrator(state, runtime, probe=probe)

        runtime.set_result("task-001", PASS_RESULT)
        runtime.set_poll_status("task-001", "done")

        orch.run_loop(max_cycles=20)
        halted = probe.of_method("orchestrator_halted")
        assert len(halted) == 1
        assert "complete" in str(halted[0]["reason"])

    def test_recovery_started_fires(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implement"),
                branch="hyperloop/task-001",
            )
        )

        probe = RecordingProbe()
        orch = _make_orchestrator(state, runtime, probe=probe)
        orch.recover()

        recovery = probe.of_method("recovery_started")
        assert len(recovery) == 1
        assert recovery[0]["in_progress_tasks"] == 1

    def test_step_executed_fires_for_action(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        step_exec = FakeStepExecutor()
        probe = RecordingProbe()

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge"),
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(
            state,
            runtime,
            process=MERGE_PROCESS,
            step_executor=step_exec,
            probe=probe,
        )
        orch.run_cycle()

        step_calls = probe.of_method("step_executed")
        assert len(step_calls) >= 1
        assert step_calls[0]["step_name"] == "merge"

    def test_signal_checked_fires_for_signal(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        signal = FakeSignalPort()
        probe = RecordingProbe()

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("await-review"),
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(
            state,
            runtime,
            process=SIGNAL_PROCESS,
            signal_port=signal,
            probe=probe,
        )
        orch.run_cycle()

        sig_calls = probe.of_method("signal_checked")
        assert len(sig_calls) >= 1
        assert sig_calls[0]["signal_name"] == "human-approval"


class TestPollInterval:
    """poll_interval causes a sleep between cycles."""

    def test_run_loop_sleeps_between_cycles(self) -> None:
        import time

        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime, poll_interval=0.05)

        start = time.monotonic()
        orch.run_loop(max_cycles=3)
        elapsed = time.monotonic() - start

        assert elapsed >= 0.1

    def test_no_sleep_after_halt(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(status=TaskStatus.COMPLETED))

        orch = _make_orchestrator(state, runtime, poll_interval=10.0)

        import time

        start = time.monotonic()
        reason = orch.run_loop(max_cycles=100)
        elapsed = time.monotonic() - start

        assert "all tasks complete" in reason.lower()
        assert elapsed < 2.0


class TestRecoverCycleDetection:
    """recover() raises RuntimeError on dependency cycles."""

    def test_recover_raises_on_cyclic_deps(self) -> None:
        import pytest

        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        state.add_task(_task(id="task-A", status=TaskStatus.IN_PROGRESS, deps=("task-B",)))
        state.add_task(_task(id="task-B", status=TaskStatus.IN_PROGRESS, deps=("task-A",)))

        orch = _make_orchestrator(state, runtime)

        with pytest.raises(RuntimeError, match=r"task-A|task-B"):
            orch.recover()

    def test_recover_does_not_raise_on_acyclic_deps(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        state.add_task(_task(id="task-A", status=TaskStatus.IN_PROGRESS, deps=("task-B",)))
        state.add_task(_task(id="task-B", status=TaskStatus.IN_PROGRESS, deps=()))

        orch = _make_orchestrator(state, runtime)
        orch.recover()


class TestHookIntegration:
    """CycleHooks are called after reap."""

    def test_hook_after_reap_called(self) -> None:

        class _FakeHook:
            def __init__(self) -> None:
                self.after_reap_calls: list[tuple[dict[str, WorkerResult], int]] = []

            def after_reap(self, *, results: dict[str, WorkerResult], cycle: int) -> None:
                self.after_reap_calls.append((dict(results), cycle))

        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        hook = _FakeHook()

        state.add_task(_task())

        orch = _make_orchestrator(state, runtime)
        orch._hooks = [hook]

        # Cycle 1: spawn
        orch.run_cycle()

        # Worker finishes
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: reap -> hook fires
        orch.run_cycle()

        assert len(hook.after_reap_calls) == 1
        results, _cycle = hook.after_reap_calls[0]
        assert "task-001" in results


BASE_DIR = Path(__file__).parent.parent / "base"


class TestPromptComposition:
    """PromptComposer is wired into the spawn path."""

    def test_spawn_uses_composed_prompt(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())
        state.set_file("specs/task-001.md", "Build a widget.")

        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)
        orch = _make_orchestrator(state, runtime, composer=composer)

        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS

    def test_spawn_without_composer_uses_empty_prompt(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime, composer=None)
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS


class TestPRLifecycle:
    """PR lifecycle: draft created at first advancing step."""

    def test_draft_pr_created_when_task_advances(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        state.add_task(_task(id="task-001", branch="hyperloop/task-001"))

        orch = _make_orchestrator(state, runtime, process=MERGE_PROCESS, pr_manager=pr_mgr)

        # Cycle 1: spawn implementer
        orch.run_cycle()
        assert state.get_task("task-001").phase == Phase("implement")
        assert state.get_task("task-001").pr is None

        # Implementer passes
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: reap implementer, advance to verify -> draft PR created
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.phase == Phase("verify")
        assert task.pr is not None
        assert "github.com" in task.pr
        assert pr_mgr.is_draft(task.pr)

    def test_no_pr_created_when_pr_manager_is_none(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        state.add_task(_task(id="task-001", branch="hyperloop/task-001"))

        orch = _make_orchestrator(state, runtime, process=MERGE_PROCESS, pr_manager=None)

        # Cycle 1: spawn implementer
        orch.run_cycle()

        # Implementer passes
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: advance to verify -- no PR
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.phase == Phase("verify")
        assert task.pr is None
