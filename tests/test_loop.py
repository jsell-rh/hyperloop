"""Tests for the orchestrator loop -- flat phase map, new ports.

Uses InMemoryStateStore, InMemoryRuntime, FakeStepExecutor, FakeSignalPort,
FakeChannelPort, RecordingProbe fakes. No mocks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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
    WorkerPollStatus,
    WorkerResult,
)
from hyperloop.loop import Orchestrator
from tests.fakes.channel import FakeChannelPort
from tests.fakes.pr import FakePRManager
from tests.fakes.probe import RecordingProbe
from tests.fakes.runtime import InMemoryRuntime
from tests.fakes.signal import FakeSignalPort
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
    gc_retention_days: int = 30,
    gc_run_every_cycles: int = 10,
    pm_max_failures: int = 5,
    spec_source: FakeSpecSource | None = None,
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
        spec_source=spec_source,
        composer=composer,
        poll_interval=poll_interval,
        probe=probe or RecordingProbe(),
        gc_retention_days=gc_retention_days,
        gc_run_every_cycles=gc_run_every_cycles,
        pm_max_failures=pm_max_failures,
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
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: reap implementer, advance to verify, spawn verifier
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("verify")

        # Simulate verifier completing with pass
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
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
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: reap implementer, advance to verify
        orch.run_cycle()
        assert state.get_task("task-001").phase == Phase("verify")

        # Verifier fails
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
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
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: advance to verify
        orch.run_cycle()

        # Verifier fails
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
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
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)
        orch.run_cycle()

        # Verifier fails -> round becomes 3 == max_task_rounds
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
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
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)
        orch.run_cycle()

        # Verifier fails -> round becomes 3 == max_task_rounds -> FAILED
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
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
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)
        runtime.set_poll_status("task-002", WorkerPollStatus.DONE)
        runtime.set_result("task-002", PASS_RESULT)

        # Cycle 2: reap both, advance to verify
        orch.run_cycle()
        assert state.get_task("task-001").phase == Phase("verify")
        assert state.get_task("task-002").phase == Phase("verify")

        # Both verifiers pass
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)
        runtime.set_poll_status("task-002", WorkerPollStatus.DONE)
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
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: advance to verify, task-002 still not eligible
        orch.run_cycle()
        assert state.get_task("task-001").phase == Phase("verify")
        assert state.get_task("task-002").status == TaskStatus.NOT_STARTED

        # task-001 verifier passes
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
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
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)

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
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
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

    def test_worker_crash_poll_failed_calls_channel(self) -> None:
        """When poll returns FAILED, channel.worker_crashed() is called."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        channel = FakeChannelPort()
        probe = RecordingProbe()

        state.add_task(_task())

        orch = _make_orchestrator(state, runtime, channel=channel, probe=probe)

        # Cycle 1: spawn implementer
        orch.run_cycle()

        # Worker crashes -- poll returns FAILED (not DONE)
        runtime.set_poll_status("task-001", WorkerPollStatus.FAILED)
        runtime.set_result(
            "task-001",
            WorkerResult(verdict=Verdict.FAIL, detail="Agent future missing or failed"),
        )

        # Cycle 2: reap crash
        orch.run_cycle()

        # Channel should have been notified
        assert len(channel.worker_crashed_calls) == 1
        task_id, role, _branch = channel.worker_crashed_calls[0]
        assert task_id == "task-001"
        assert role == "implementer"

    def test_worker_crash_poll_failed_emits_probe(self) -> None:
        """When poll returns FAILED, probe.worker_crash_detected is emitted."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()

        state.add_task(_task())

        orch = _make_orchestrator(state, runtime, probe=probe)

        # Cycle 1: spawn implementer
        orch.run_cycle()

        # Worker crashes -- poll returns FAILED
        runtime.set_poll_status("task-001", WorkerPollStatus.FAILED)
        runtime.set_result(
            "task-001",
            WorkerResult(verdict=Verdict.FAIL, detail="Agent future missing or failed"),
        )

        # Cycle 2: reap crash
        orch.run_cycle()

        crash_calls = probe.of_method("worker_crash_detected")
        assert len(crash_calls) == 1
        assert crash_calls[0]["task_id"] == "task-001"
        assert crash_calls[0]["role"] == "implementer"

    def test_normal_failure_does_not_call_channel_crashed(self) -> None:
        """When poll returns DONE with verdict FAIL, worker_crashed is NOT called."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        channel = FakeChannelPort()
        probe = RecordingProbe()

        state.add_task(_task())

        orch = _make_orchestrator(state, runtime, channel=channel, probe=probe)

        # Cycle 1: spawn implementer
        orch.run_cycle()

        # Worker completes normally with FAIL verdict (poll returns DONE)
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", FAIL_RESULT)

        # Cycle 2: reap normal failure
        orch.run_cycle()

        # Channel should NOT have been notified about a crash
        assert len(channel.worker_crashed_calls) == 0

        # Probe should NOT have crash_detected
        crash_calls = probe.of_method("worker_crash_detected")
        assert len(crash_calls) == 0


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
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)

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
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
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
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
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
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: advance to verify -- no PR
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.phase == Phase("verify")
        assert task.pr is None


# ---------------------------------------------------------------------------
# Reconciler integration tests
# ---------------------------------------------------------------------------


class TestDeletedSpecRetiresTasks:
    """Tasks referencing a deleted spec are transitioned to FAILED."""

    def test_deleted_spec_retires_in_progress_task(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()

        # Task references specs/task-001.md but that spec is NOT in the file system
        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implement"),
                branch="hyperloop/task-001",
            )
        )
        # Seed a different spec so the store has spec files (triggers deleted-spec check)
        # but task-001's spec_ref "specs/task-001.md" has no backing file
        state.set_file("specs/other.md", "Some other spec")

        orch = _make_orchestrator(state, runtime, probe=probe)
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.FAILED

    def test_deleted_spec_emits_task_failed_probe(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()

        state.add_task(
            _task(
                id="task-orphan",
                status=TaskStatus.NOT_STARTED,
            )
        )
        # Seed a different spec so deleted-spec detection is active
        state.set_file("specs/other.md", "Some other spec")

        orch = _make_orchestrator(state, runtime, probe=probe)
        orch.run_cycle()

        failed_calls = probe.of_method("task_failed")
        orphan_calls = [c for c in failed_calls if c["task_id"] == "task-orphan"]
        assert len(orphan_calls) >= 1
        assert "spec deleted" in str(orphan_calls[0]["reason"])

    def test_completed_tasks_not_retired_on_deleted_spec(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        # Completed tasks should not be retired -- they are GC eligible instead
        state.add_task(_task(id="task-done", status=TaskStatus.COMPLETED))

        orch = _make_orchestrator(state, runtime)
        orch.run_cycle()

        task = state.get_task("task-done")
        assert task.status == TaskStatus.COMPLETED


class TestPMFailureBackoff:
    """PM failure triggers backoff and eventually halt."""

    def test_pm_failure_increments_counter(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        # Need at least one task so the cycle doesn't exit early
        state.add_task(_task(id="task-001"))
        state.set_file("specs/task-001.md", "Existing spec")
        # Seed an additional uncovered spec so intake is triggered
        state.set_file("specs/new.spec.md", "New spec")
        runtime.set_serial_default_success(False)

        orch = _make_orchestrator(state, runtime, composer=composer, probe=probe)
        orch.run_cycle()

        assert orch._pm_consecutive_failures >= 1

    def test_pm_failure_halt_after_max(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        # Task + spec so the cycle doesn't exit early
        state.add_task(_task(id="task-001"))
        state.set_file("specs/task-001.md", "Existing spec")
        state.set_file("specs/new.spec.md", "New spec")
        runtime.set_serial_default_success(False)

        orch = _make_orchestrator(state, runtime, composer=composer, probe=probe, pm_max_failures=3)

        # Run enough cycles for 3 consecutive PM failures
        halt_reason: str | None = None
        for i in range(10):
            halt_reason = orch.run_cycle(cycle_num=i + 1)
            if halt_reason is not None:
                break

        assert halt_reason is not None
        assert "pm" in halt_reason.lower()


class TestGCPrunesTerminalTasks:
    """GC prunes terminal tasks past retention period."""

    def test_gc_prunes_completed_tasks_past_retention(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()

        state.add_task(_task(id="task-old", status=TaskStatus.COMPLETED))
        state.add_task(
            _task(id="task-active", status=TaskStatus.IN_PROGRESS, phase=Phase("implement"))
        )
        # Seed spec files so deleted-spec detection doesn't interfere
        state.set_file("specs/task-old.md", "old spec")
        state.set_file("specs/task-active.md", "active spec")

        orch = _make_orchestrator(
            state,
            runtime,
            probe=probe,
            gc_retention_days=30,
            gc_run_every_cycles=1,
        )
        # Inject task ages: task-old is 45 days, task-active is 1 day
        orch._task_ages = {"task-old": 45.0, "task-active": 1.0}

        orch.run_cycle()

        # task-old should be pruned
        with pytest.raises(KeyError):
            state.get_task("task-old")

        # task-active should remain
        task = state.get_task("task-active")
        assert task.status == TaskStatus.IN_PROGRESS

    def test_gc_emits_probe(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()

        state.add_task(_task(id="task-old", status=TaskStatus.COMPLETED))
        state.set_file("specs/task-old.md", "old spec")

        orch = _make_orchestrator(
            state,
            runtime,
            probe=probe,
            gc_retention_days=30,
            gc_run_every_cycles=1,
        )
        orch._task_ages = {"task-old": 45.0}

        orch.run_cycle()

        gc_calls = probe.of_method("gc_ran")
        assert len(gc_calls) >= 1
        assert gc_calls[0]["pruned_count"] == 1

    def test_gc_only_runs_on_configured_interval(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()

        state.add_task(_task(id="task-old", status=TaskStatus.COMPLETED))
        state.set_file("specs/task-old.md", "old spec")

        orch = _make_orchestrator(
            state,
            runtime,
            probe=probe,
            gc_retention_days=30,
            gc_run_every_cycles=5,
        )
        orch._task_ages = {"task-old": 45.0}

        # Cycle 1: GC should not run (not on interval)
        orch.run_cycle(cycle_num=1)
        gc_calls = probe.of_method("gc_ran")
        assert len(gc_calls) == 0

        # Cycle 5: GC should run
        orch.run_cycle(cycle_num=5)
        gc_calls = probe.of_method("gc_ran")
        assert len(gc_calls) == 1


class TestPhaseOrphanDetection:
    """Tasks at phases not in current phase map are reset."""

    def test_orphaned_phase_resets_task(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()

        # Task is at phase "code-review" which doesn't exist in DEFAULT_PROCESS
        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("code-review"),
                round=3,
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(state, runtime, probe=probe)
        orch.run_cycle()

        task = state.get_task("task-001")
        # Should be reset to first phase
        assert task.phase is None or task.phase == Phase("implement")
        assert task.status in (TaskStatus.NOT_STARTED, TaskStatus.IN_PROGRESS)

    def test_orphaned_phase_emits_task_reset_probe(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("code-review"),
                round=3,
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(state, runtime, probe=probe)
        orch.run_cycle()

        reset_calls = probe.of_method("task_reset")
        assert len(reset_calls) >= 1
        assert reset_calls[0]["task_id"] == "task-001"
        assert "process changed" in str(reset_calls[0]["reason"]).lower()


# ---------------------------------------------------------------------------
# Gap #1: Drift detection wired into reconciler
# ---------------------------------------------------------------------------


class TestCoverageGapTriggersIntake:
    """Coverage gap detected by reconciler triggers PM intake."""

    def test_coverage_gap_triggers_intake(self) -> None:
        """When a spec has no tasks, drift is detected and intake runs."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        # Seed an existing task so the cycle doesn't exit early
        state.add_task(_task(id="task-001"))
        state.set_file("specs/task-001.md", "Existing spec")

        # Add an uncovered spec -- no task references it
        state.set_file("specs/uncovered.spec.md", "Uncovered spec content")

        spec_source = FakeSpecSource()
        spec_source.add_spec("specs/uncovered.spec.md", "Uncovered spec content")
        spec_source.add_spec("specs/task-001.md", "Existing spec")
        spec_source.set_version("abc123")

        orch = _make_orchestrator(
            state, runtime, composer=composer, probe=probe, spec_source=spec_source
        )
        orch.run_cycle()

        # Coverage drift should have been detected
        drift_calls = probe.of_method("drift_detected")
        coverage_drifts = [c for c in drift_calls if c["drift_type"] == "coverage"]
        assert len(coverage_drifts) >= 1
        assert any("uncovered" in str(c["spec_path"]) for c in coverage_drifts)

    def test_coverage_gap_causes_intake_to_run(self) -> None:
        """When coverage gaps exist, intake runs even without prior failures."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        state.add_task(_task(id="task-001"))
        state.set_file("specs/task-001.md", "Existing spec")
        state.set_file("specs/uncovered.spec.md", "Uncovered spec")

        spec_source = FakeSpecSource()
        spec_source.add_spec("specs/uncovered.spec.md", "Uncovered spec")
        spec_source.add_spec("specs/task-001.md", "Existing spec")
        spec_source.set_version("abc123")

        orch = _make_orchestrator(
            state, runtime, composer=composer, probe=probe, spec_source=spec_source
        )
        orch.run_cycle()

        intake_calls = probe.of_method("intake_ran")
        assert len(intake_calls) >= 1


class TestFreshnessDriftTriggersIntake:
    """Freshness drift detected by reconciler triggers PM intake."""

    def test_freshness_drift_triggers_intake(self) -> None:
        """When a spec SHA changes, freshness drift is detected."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        # Task pinned to old SHA
        state.add_task(
            Task(
                id="task-001",
                title="Task task-001",
                spec_ref="specs/auth.md@oldsha",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implement"),
                deps=(),
                round=0,
                branch="hyperloop/task-001",
                pr=None,
            )
        )
        state.set_file("specs/auth.md", "Auth spec content")

        spec_source = FakeSpecSource()
        spec_source.add_spec("specs/auth.md", "Auth spec content")
        spec_source.set_version("newsha")

        orch = _make_orchestrator(
            state, runtime, composer=composer, probe=probe, spec_source=spec_source
        )
        orch.run_cycle()

        drift_calls = probe.of_method("drift_detected")
        freshness_drifts = [c for c in drift_calls if c["drift_type"] == "freshness"]
        assert len(freshness_drifts) >= 1
        assert any("auth" in str(c["spec_path"]) for c in freshness_drifts)


# ---------------------------------------------------------------------------
# Gap #2: Convergence tracking with auditor
# ---------------------------------------------------------------------------


class TestConvergenceTracking:
    """All tasks completed for a spec triggers auditor, marks converged."""

    def test_all_tasks_completed_triggers_auditor(self) -> None:
        """When all tasks for a spec are completed, auditor runs."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        state.add_task(
            Task(
                id="task-001",
                title="Task 001",
                spec_ref="specs/auth.md@abc123",
                status=TaskStatus.COMPLETED,
                phase=None,
                deps=(),
                round=1,
                branch="hyperloop/task-001",
                pr=None,
            )
        )
        state.set_file("specs/auth.md", "Auth spec content")

        spec_source = FakeSpecSource()
        spec_source.add_spec("specs/auth.md", "Auth spec content")
        spec_source.set_version("abc123")

        orch = _make_orchestrator(
            state, runtime, composer=composer, probe=probe, spec_source=spec_source
        )
        # Auditor passes (run_serial returns True)
        runtime.set_serial_default_success(True)

        orch.run_cycle()

        # Auditor should have been invoked via run_serial
        auditor_runs = [r for r in runtime.serial_runs if r.role == "auditor"]
        assert len(auditor_runs) >= 1

        # Spec should be marked converged
        convergence_calls = probe.of_method("convergence_marked")
        assert len(convergence_calls) >= 1
        assert convergence_calls[0]["spec_ref"] == "specs/auth.md@abc123"

    def test_converged_spec_not_re_audited(self) -> None:
        """A spec already marked converged should not be audited again."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        state.add_task(
            Task(
                id="task-001",
                title="Task 001",
                spec_ref="specs/auth.md@abc123",
                status=TaskStatus.COMPLETED,
                phase=None,
                deps=(),
                round=1,
                branch="hyperloop/task-001",
                pr=None,
            )
        )
        state.set_file("specs/auth.md", "Auth spec content")

        spec_source = FakeSpecSource()
        spec_source.add_spec("specs/auth.md", "Auth spec content")
        spec_source.set_version("abc123")

        orch = _make_orchestrator(
            state, runtime, composer=composer, probe=probe, spec_source=spec_source
        )
        runtime.set_serial_default_success(True)

        # Pre-mark spec as converged
        orch._converged_specs.add("specs/auth.md@abc123")

        orch.run_cycle()

        # No auditor should have run
        auditor_runs = [r for r in runtime.serial_runs if r.role == "auditor"]
        assert len(auditor_runs) == 0

    def test_auditor_failure_does_not_mark_converged(self) -> None:
        """When auditor finds misalignment, spec is NOT marked converged."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        state.add_task(
            Task(
                id="task-001",
                title="Task 001",
                spec_ref="specs/auth.md@abc123",
                status=TaskStatus.COMPLETED,
                phase=None,
                deps=(),
                round=1,
                branch="hyperloop/task-001",
                pr=None,
            )
        )
        state.set_file("specs/auth.md", "Auth spec content")

        spec_source = FakeSpecSource()
        spec_source.add_spec("specs/auth.md", "Auth spec content")
        spec_source.set_version("abc123")

        orch = _make_orchestrator(
            state, runtime, composer=composer, probe=probe, spec_source=spec_source
        )
        # Auditor fails (misaligned)
        runtime.set_serial_default_success(False)

        orch.run_cycle()

        # Spec should NOT be converged
        assert "specs/auth.md@abc123" not in orch._converged_specs

        # Audit event should show misaligned
        audit_calls = probe.of_method("audit_ran")
        assert len(audit_calls) >= 1
        assert audit_calls[0]["result"] == "misaligned"


# ---------------------------------------------------------------------------
# Gap #3: PM backoff implementation
# ---------------------------------------------------------------------------


class TestPMBackoffSkipsIntake:
    """PM backoff: after failure, intake is skipped for N cycles."""

    def test_pm_backoff_skips_intake_for_n_cycles(self) -> None:
        """After PM failure, intake should be skipped during backoff period."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        state.add_task(_task(id="task-001"))
        state.set_file("specs/task-001.md", "Existing spec")
        state.set_file("specs/uncovered.spec.md", "Uncovered spec")
        runtime.set_serial_default_success(False)

        spec_source = FakeSpecSource()
        spec_source.add_spec("specs/uncovered.spec.md", "Uncovered spec")
        spec_source.add_spec("specs/task-001.md", "Existing spec")
        spec_source.set_version("abc123")

        orch = _make_orchestrator(
            state,
            runtime,
            composer=composer,
            probe=probe,
            pm_max_failures=10,
            spec_source=spec_source,
        )

        # Cycle 1: PM fails, backoff activated
        orch.run_cycle(cycle_num=1)
        assert orch._pm_consecutive_failures >= 1

        # Record how many serial runs happened up to now
        serial_count_after_first = len(runtime.serial_runs)

        # Cycle 2: Should skip intake due to backoff
        orch.run_cycle(cycle_num=2)

        # During backoff, PM (serial) should not be invoked
        pm_intake_runs = [
            r for r in runtime.serial_runs[serial_count_after_first:] if r.role == "pm"
        ]
        assert len(pm_intake_runs) == 0

    def test_pm_backoff_exponential(self) -> None:
        """PM backoff uses exponential backoff (2^failures)."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        state.add_task(_task(id="task-001"))
        state.set_file("specs/task-001.md", "Existing spec")
        state.set_file("specs/uncovered.spec.md", "Uncovered spec")
        runtime.set_serial_default_success(False)

        spec_source = FakeSpecSource()
        spec_source.add_spec("specs/uncovered.spec.md", "Uncovered spec")
        spec_source.add_spec("specs/task-001.md", "Existing spec")
        spec_source.set_version("abc123")

        orch = _make_orchestrator(
            state,
            runtime,
            composer=composer,
            probe=probe,
            pm_max_failures=10,
            spec_source=spec_source,
        )

        # First failure: backoff = 2^1 = 2 cycles
        orch.run_cycle(cycle_num=1)
        assert orch._pm_skip_until >= 3  # current_cycle(1) + 2 = 3


# ---------------------------------------------------------------------------
# Gap #6: Failure details passed to PM
# ---------------------------------------------------------------------------


class TestPMReceivesFailureDetails:
    """PM receives failure details (not just IDs) in prompt."""

    def test_pm_receives_failure_details_in_prompt(self) -> None:
        """When intake runs due to failures, PM prompt includes failure detail."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        # Create a failed task with review detail
        state.add_task(_task(id="task-fail", status=TaskStatus.FAILED))
        state.set_file("specs/task-fail.md", "Failing spec")
        state.store_review("task-fail", 1, "verifier", "fail", "timeout handling missing")

        # Need an uncovered spec to trigger intake, or rely on has_failures
        state.set_file("specs/new.spec.md", "New spec")

        spec_source = FakeSpecSource()
        spec_source.add_spec("specs/task-fail.md", "Failing spec")
        spec_source.add_spec("specs/new.spec.md", "New spec")
        spec_source.set_version("abc123")

        orch = _make_orchestrator(
            state, runtime, composer=composer, probe=probe, spec_source=spec_source
        )
        # Set has_failures flag so intake triggers with failure context
        orch._has_failures_since_intake = True

        orch.run_cycle(cycle_num=1)

        # PM should have been called
        pm_runs = [r for r in runtime.serial_runs if r.role == "pm"]
        assert len(pm_runs) >= 1

        # The prompt should contain the actual failure detail, not just the task ID
        pm_prompt = pm_runs[0].prompt
        assert "timeout handling missing" in pm_prompt


# ---------------------------------------------------------------------------
# Gap: GC writes summaries before deleting tasks
# ---------------------------------------------------------------------------


class TestGCWritesSummary:
    """GC must write a summary record before deleting a task."""

    def test_gc_writes_summary_before_delete(self) -> None:
        """After GC prunes a completed task, a summary exists in the state store."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()

        state.add_task(
            Task(
                id="task-old",
                title="Old task",
                spec_ref="specs/auth.md@abc123",
                status=TaskStatus.COMPLETED,
                phase=None,
                deps=(),
                round=2,
                branch="hyperloop/task-old",
                pr=None,
            )
        )
        state.set_file("specs/auth.md", "Auth spec content")

        orch = _make_orchestrator(
            state,
            runtime,
            probe=probe,
            gc_retention_days=30,
            gc_run_every_cycles=1,
        )
        orch._task_ages = {"task-old": 45.0}

        orch.run_cycle()

        # Task should be pruned
        with pytest.raises(KeyError):
            state.get_task("task-old")

        # Summary should exist for the spec
        summary_content = state.get_summary("specs/auth.md")
        assert summary_content is not None
        assert "auth.md" in summary_content
        assert "abc123" in summary_content

    def test_gc_writes_summary_for_failed_task(self) -> None:
        """GC writes summary for failed tasks too, with failed count."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()

        state.add_task(
            Task(
                id="task-fail",
                title="Failed task",
                spec_ref="specs/widget.md@def456",
                status=TaskStatus.FAILED,
                phase=None,
                deps=(),
                round=5,
                branch="hyperloop/task-fail",
                pr=None,
            )
        )
        state.set_file("specs/widget.md", "Widget spec content")

        orch = _make_orchestrator(
            state,
            runtime,
            probe=probe,
            gc_retention_days=30,
            gc_run_every_cycles=1,
        )
        orch._task_ages = {"task-fail": 45.0}

        orch.run_cycle()

        summary_content = state.get_summary("specs/widget.md")
        assert summary_content is not None
        assert "failed" in summary_content


# ---------------------------------------------------------------------------
# Gap: Summary-aware coverage prevents re-creation
# ---------------------------------------------------------------------------


class TestSummaryPreventsCoverageGap:
    """A summary record prevents coverage gap detection after GC prunes tasks."""

    def test_summary_prevents_coverage_gap(self) -> None:
        """After GC prunes a task, next coverage check finds summary and skips intake."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()

        # Another task exists so the cycle doesn't halt
        state.add_task(
            _task(
                id="task-active",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implement"),
            )
        )
        state.set_file("specs/task-active.md", "Active spec")
        # Spec exists but has no task (was GC'd)
        state.set_file("specs/auth.md", "Auth spec content")

        # Pre-store a summary for auth.md (as if GC wrote it)
        import yaml

        summary_data = yaml.dump(
            {
                "spec_path": "specs/auth.md",
                "spec_ref": "specs/auth.md@abc123",
                "total_tasks": 1,
                "completed": 1,
                "failed": 0,
                "failure_themes": [],
                "last_audit": None,
                "last_audit_result": None,
            }
        )
        state.store_summary("specs/auth.md", summary_data)

        spec_source = FakeSpecSource()
        spec_source.add_spec("specs/auth.md", "Auth spec content")
        spec_source.add_spec("specs/task-active.md", "Active spec")
        spec_source.set_version("abc123")

        orch = _make_orchestrator(state, runtime, probe=probe, spec_source=spec_source)
        orch.run_cycle()

        # Should NOT detect coverage gap for auth.md
        drift_calls = probe.of_method("drift_detected")
        coverage_drifts = [
            c
            for c in drift_calls
            if c["drift_type"] == "coverage" and "auth" in str(c["spec_path"])
        ]
        assert len(coverage_drifts) == 0

    def test_summary_with_stale_sha_does_not_prevent_coverage_gap(self) -> None:
        """Summary exists but spec SHA changed -- coverage gap should still trigger."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()

        state.add_task(
            _task(
                id="task-active",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implement"),
            )
        )
        state.set_file("specs/task-active.md", "Active spec")
        state.set_file("specs/auth.md", "Auth spec content v2")

        import yaml

        # Summary references old SHA
        summary_data = yaml.dump(
            {
                "spec_path": "specs/auth.md",
                "spec_ref": "specs/auth.md@oldsha",
                "total_tasks": 1,
                "completed": 1,
                "failed": 0,
                "failure_themes": [],
                "last_audit": None,
                "last_audit_result": None,
            }
        )
        state.store_summary("specs/auth.md", summary_data)

        spec_source = FakeSpecSource()
        spec_source.add_spec("specs/auth.md", "Auth spec content v2")
        spec_source.add_spec("specs/task-active.md", "Active spec")
        spec_source.set_version("newsha")  # Different from summary's oldsha

        orch = _make_orchestrator(state, runtime, probe=probe, spec_source=spec_source)
        orch.run_cycle()

        # Should detect freshness drift for auth.md (summary has stale SHA)
        drift_calls = probe.of_method("drift_detected")
        auth_drifts = [c for c in drift_calls if "auth" in str(c["spec_path"])]
        assert len(auth_drifts) >= 1


# ---------------------------------------------------------------------------
# Gap: Audit misalignment stores finding
# ---------------------------------------------------------------------------


class TestAuditMisalignmentStoresFinding:
    """When auditor finds misalignment, finding is stored in state store."""

    def test_audit_misalignment_stores_finding(self) -> None:
        """Auditor fails -> finding stored as review in state."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        state.add_task(
            Task(
                id="task-001",
                title="Task 001",
                spec_ref="specs/auth.md@abc123",
                status=TaskStatus.COMPLETED,
                phase=None,
                deps=(),
                round=1,
                branch="hyperloop/task-001",
                pr=None,
            )
        )
        state.set_file("specs/auth.md", "Auth spec content")

        spec_source = FakeSpecSource()
        spec_source.add_spec("specs/auth.md", "Auth spec content")
        spec_source.set_version("abc123")

        orch = _make_orchestrator(
            state, runtime, composer=composer, probe=probe, spec_source=spec_source
        )
        # Auditor fails (misaligned)
        runtime.set_serial_default_success(False)

        orch.run_cycle()

        # A review should have been stored for the audit finding
        findings = state.get_findings("audit-specs/auth.md@abc123")
        assert findings != ""

    def test_audit_finding_passed_to_pm(self) -> None:
        """After audit failure, PM intake includes audit finding in prompt."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        state.add_task(
            Task(
                id="task-001",
                title="Task 001",
                spec_ref="specs/auth.md@abc123",
                status=TaskStatus.COMPLETED,
                phase=None,
                deps=(),
                round=1,
                branch="hyperloop/task-001",
                pr=None,
            )
        )
        state.set_file("specs/auth.md", "Auth spec content")
        # Add an uncovered spec so PM intake triggers
        state.set_file("specs/uncovered.spec.md", "New spec")

        spec_source = FakeSpecSource()
        spec_source.add_spec("specs/auth.md", "Auth spec content")
        spec_source.add_spec("specs/uncovered.spec.md", "New spec")
        spec_source.set_version("abc123")

        orch = _make_orchestrator(
            state, runtime, composer=composer, probe=probe, spec_source=spec_source
        )
        # Auditor fails (misaligned) -- this sets _has_drift = True
        runtime.set_serial_default_success(False)

        orch.run_cycle()

        # Drift should have been detected (misalignment sets _has_drift)
        assert any(c["result"] == "misaligned" for c in probe.of_method("audit_ran"))

        # PM intake should have been triggered (because _has_drift was set)
        pm_runs = [r for r in runtime.serial_runs if r.role == "pm"]
        assert len(pm_runs) >= 1
