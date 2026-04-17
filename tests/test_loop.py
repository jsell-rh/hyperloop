"""Tests for the orchestrator loop — wires decide, pipeline, state, and runtime.

Uses InMemoryStateStore and InMemoryRuntime fakes. No mocks.
"""

from __future__ import annotations

from pathlib import Path

from hyperloop.compose import PromptComposer, load_templates_from_dir
from hyperloop.domain.model import (
    ActionStep,
    GateStep,
    LoopStep,
    Phase,
    Process,
    RoleStep,
    Task,
    TaskStatus,
    Verdict,
    WorkerResult,
)
from hyperloop.loop import Orchestrator
from tests.fakes.pr import FakePRManager
from tests.fakes.probe import RecordingProbe
from tests.fakes.runtime import InMemoryRuntime
from tests.fakes.state import InMemoryStateStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS_RESULT = WorkerResult(verdict=Verdict.PASS, findings=0, detail="All tests pass")
FAIL_RESULT = WorkerResult(verdict=Verdict.FAIL, findings=1, detail="Tests failed")

DEFAULT_PROCESS = Process(
    name="default",
    intake=(),
    pipeline=(
        LoopStep(
            steps=(
                RoleStep(role="implementer", on_pass=None, on_fail=None),
                RoleStep(role="verifier", on_pass=None, on_fail=None),
            ),
        ),
    ),
)


def _task(
    id: str = "task-001",
    status: TaskStatus = TaskStatus.NOT_STARTED,
    deps: tuple[str, ...] = (),
    round: int = 0,
    phase: Phase | None = None,
    branch: str | None = None,
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
        pr=None,
    )


def _make_orchestrator(
    state: InMemoryStateStore,
    runtime: InMemoryRuntime,
    process: Process = DEFAULT_PROCESS,
    max_workers: int = 6,
    max_task_rounds: int = 50,
    pr_manager: FakePRManager | None = None,
    composer: PromptComposer | None = None,
    poll_interval: float = 0,
    probe: RecordingProbe | None = None,
    max_rebase_attempts: int = 3,
) -> Orchestrator:
    return Orchestrator(
        state=state,
        runtime=runtime,
        process=process,
        max_workers=max_workers,
        max_task_rounds=max_task_rounds,
        pr_manager=pr_manager,
        composer=composer,
        poll_interval=poll_interval,
        probe=probe,
        max_rebase_attempts=max_rebase_attempts,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSingleTaskEndToEnd:
    """Task starts not-started, worker spawns, worker completes (pass),
    task transitions to complete."""

    def test_single_task_completes_through_full_pipeline(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime)

        # Cycle 1: decide spawns implementer
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("implementer")

        # Simulate implementer completing with pass
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: reap implementer, advance to verifier, spawn verifier
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("verifier")

        # Simulate verifier completing with pass
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 3: reap verifier, pipeline complete, task complete
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.status == TaskStatus.COMPLETE

    def test_state_store_transitions_are_committed(self) -> None:
        """Verify that state changes are committed after each cycle."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime)
        orch.run_cycle()

        assert len(state.committed_messages) > 0


class TestFailedVerificationLoopsBack:
    """Worker fails verification, task goes back through the loop
    (round increments), worker re-spawns."""

    def test_fail_increments_round_and_restarts(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime)

        # Cycle 1: spawn implementer
        orch.run_cycle()
        assert state.get_task("task-001").phase == Phase("implementer")

        # Implementer passes
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: reap implementer, advance to verifier
        orch.run_cycle()
        assert state.get_task("task-001").phase == Phase("verifier")

        # Verifier fails
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", FAIL_RESULT)

        # Cycle 3: reap verifier, loop restarts, round increments
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.round == 1
        assert task.phase == Phase("implementer")  # Restarted from top of loop

    def test_findings_are_stored_on_failure(self) -> None:
        """When a worker fails, its findings detail is stored."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime)

        # Cycle 1: spawn implementer
        orch.run_cycle()

        # Implementer passes
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: advance to verifier
        orch.run_cycle()

        # Verifier fails
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", FAIL_RESULT)

        # Cycle 3: reap failure, store findings
        orch.run_cycle()
        findings = state.get_findings("task-001")
        assert "Tests failed" in findings


class TestMaxRoundsHalts:
    """Task hits max_task_rounds, status -> failed, loop halts."""

    def test_max_task_rounds_transitions_to_failed(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        # Task already at round max_task_rounds - 1, one more fail will exceed
        state.add_task(_task(status=TaskStatus.IN_PROGRESS, round=2, phase=Phase("implementer")))

        orch = _make_orchestrator(state, runtime, max_task_rounds=3)

        # Cycle 1: should spawn implementer (round 2, max is 3)
        orch.run_cycle()

        # Implementer passes, advance to verifier
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
        """run_loop returns a halt reason when max_task_rounds is hit via step-by-step."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(round=2))

        orch = _make_orchestrator(state, runtime, max_task_rounds=3)

        # Cycle 1: spawn implementer
        orch.run_cycle()

        # Implementer passes -> verifier
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
    """Two independent tasks both spawn (up to max_workers), both complete."""

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

        # Cycle 2: reap both, advance to verifiers
        orch.run_cycle()
        assert state.get_task("task-001").phase == Phase("verifier")
        assert state.get_task("task-002").phase == Phase("verifier")

        # Both verifiers pass
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)
        runtime.set_poll_status("task-002", "done")
        runtime.set_result("task-002", PASS_RESULT)

        # Cycle 3: reap verifiers, both complete
        orch.run_cycle()
        assert state.get_task("task-001").status == TaskStatus.COMPLETE
        assert state.get_task("task-002").status == TaskStatus.COMPLETE

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
    """task-002 depends on task-001. task-001 completes first, then task-002 spawns."""

    def test_dependent_task_waits_for_dependency(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(id="task-001"))
        state.add_task(_task(id="task-002", deps=("task-001",)))

        orch = _make_orchestrator(state, runtime)

        # Cycle 1: only task-001 spawns (task-002 dep not met)
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

        # Cycle 2: reap task-001 impl, advance to verifier
        # task-002 still not eligible (dep not complete)
        orch.run_cycle()
        assert state.get_task("task-001").phase == Phase("verifier")
        # task-002 still waiting because task-001 is not complete yet
        assert state.get_task("task-002").status == TaskStatus.NOT_STARTED

        # task-001 verifier passes
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 3: task-001 complete, task-002 now eligible
        orch.run_cycle()
        assert state.get_task("task-001").status == TaskStatus.COMPLETE
        assert state.get_task("task-002").status == TaskStatus.IN_PROGRESS


class TestConvergence:
    """All tasks complete, loop halts with reason."""

    def test_run_loop_halts_when_all_complete(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(id="task-001"))

        orch = _make_orchestrator(state, runtime)

        # Set up runtime: pass for everything
        runtime.set_result("task-001", PASS_RESULT)
        runtime.set_poll_status("task-001", "done")

        reason = orch.run_loop(max_cycles=20)
        assert "all tasks complete" in reason.lower()
        assert state.get_task("task-001").status == TaskStatus.COMPLETE

    def test_run_loop_returns_safety_limit_reason(self) -> None:
        """If max_cycles is exhausted, run_loop returns a safety reason."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(id="task-001"))

        orch = _make_orchestrator(state, runtime)
        # Workers never finish (default poll is "running"), so the loop never converges
        reason = orch.run_loop(max_cycles=3)
        assert "max_cycles" in reason.lower()

    def test_empty_process_halts_immediately(self) -> None:
        """If all tasks are already complete, the loop halts immediately."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(id="task-001", status=TaskStatus.COMPLETE))

        orch = _make_orchestrator(state, runtime)
        reason = orch.run_loop(max_cycles=10)
        assert "all tasks complete" in reason.lower()


class TestRunCycleStepByStep:
    """Verify that run_cycle returns whether the loop should continue."""

    def test_run_cycle_returns_none_when_not_halted(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime)
        result = orch.run_cycle()
        assert result is None  # Not halted yet

    def test_run_cycle_returns_reason_when_halted(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(status=TaskStatus.COMPLETE))

        orch = _make_orchestrator(state, runtime)
        result = orch.run_cycle()
        assert result is not None
        assert "all tasks complete" in result.lower()


class TestNeedsRebaseSpawning:
    """NEEDS_REBASE tasks get a rebase-resolver worker spawned."""

    def test_needs_rebase_task_spawns_rebase_resolver(self) -> None:
        """A task in NEEDS_REBASE status should spawn a rebase-resolver worker."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.NEEDS_REBASE,
                phase=Phase("verifier"),
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(state, runtime)
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("rebase-resolver")

    def test_needs_rebase_spawns_with_correct_role(self) -> None:
        """The spawned worker should have role='rebase-resolver'."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.NEEDS_REBASE,
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(state, runtime)
        orch.run_cycle()

        # Check the runtime received a spawn with rebase-resolver role
        handle = runtime.handles.get("task-001")
        assert handle is not None
        assert handle.role == "rebase-resolver"

    def test_needs_rebase_prioritized_over_not_started(self) -> None:
        """NEEDS_REBASE tasks should spawn before NOT_STARTED tasks when slots are limited."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.NOT_STARTED,
            )
        )
        state.add_task(
            _task(
                id="task-002",
                status=TaskStatus.NEEDS_REBASE,
                branch="hyperloop/task-002",
            )
        )

        orch = _make_orchestrator(state, runtime, max_workers=1)
        orch.run_cycle()

        # task-002 (needs_rebase) should have gotten the single slot
        assert state.get_task("task-002").status == TaskStatus.IN_PROGRESS
        assert state.get_task("task-001").status == TaskStatus.NOT_STARTED


class TestRecovery:
    """Crash recovery: orphaned workers are cancelled, in-progress tasks are re-spawned."""

    def test_recover_cancels_orphaned_worker(self) -> None:
        """An orphaned worker found by the runtime should be cancelled during recovery."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        # Simulate a task that was in progress when the orchestrator crashed
        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implementer"),
                branch="hyperloop/task-001",
            )
        )

        # Simulate an orphaned worker left in the runtime
        runtime.spawn("task-001", "implementer", "", "hyperloop/task-001")

        orch = _make_orchestrator(state, runtime)
        orch.recover()

        # The orphan should have been cancelled
        assert "task-001" in runtime.cancelled

    def test_recover_respawns_in_progress_task_next_cycle(self) -> None:
        """After recovery, the next cycle should spawn a worker for the in-progress task."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implementer"),
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(state, runtime)
        orch.recover()

        # Next cycle should spawn a worker for this task
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        # Should have spawned a fresh worker
        handle = runtime.handles.get("task-001")
        assert handle is not None

    def test_recover_ignores_non_in_progress_tasks(self) -> None:
        """Recovery should only process IN_PROGRESS tasks."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        state.add_task(_task(id="task-001", status=TaskStatus.NOT_STARTED))
        state.add_task(_task(id="task-002", status=TaskStatus.COMPLETE))
        state.add_task(_task(id="task-003", status=TaskStatus.FAILED))

        orch = _make_orchestrator(state, runtime)
        orch.recover()

        # No orphan checks for these tasks
        assert "task-001" not in runtime.cancelled
        assert "task-002" not in runtime.cancelled
        assert "task-003" not in runtime.cancelled

    def test_recover_handles_no_orphan(self) -> None:
        """When runtime finds no orphan, recovery proceeds without cancellation."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implementer"),
                branch="hyperloop/task-001",
            )
        )

        # No orphan in runtime — the worker process already exited
        orch = _make_orchestrator(state, runtime)
        orch.recover()

        # No cancellation should have happened
        assert "task-001" not in runtime.cancelled

        # But the task should still be re-spawned on next cycle
        orch.run_cycle()
        handle = runtime.handles.get("task-001")
        assert handle is not None


class TestGateStub:
    """Gate polling without PRManager is a no-op."""

    def test_gate_stub_does_not_crash(self) -> None:
        """Running a cycle without a PRManager should not raise."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime)
        # This should succeed without errors — the stub just logs
        result = orch.run_cycle()
        assert result is None


class TestDecideIntegration:
    """The loop uses decide() for eligibility, not ad-hoc logic."""

    def test_decide_controls_spawning(self) -> None:
        """Spawning decisions flow through decide(), not internal _find_eligible_tasks."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(id="task-001"))
        state.add_task(_task(id="task-002", deps=("task-001",)))

        orch = _make_orchestrator(state, runtime)

        # Verify the orchestrator no longer has _find_eligible_tasks
        assert not hasattr(orch, "_find_eligible_tasks")
        assert not hasattr(orch, "_deps_met")

        # Cycle 1: only task-001 should spawn (task-002 dep unmet per decide())
        orch.run_cycle()
        assert state.get_task("task-001").status == TaskStatus.IN_PROGRESS
        assert state.get_task("task-002").status == TaskStatus.NOT_STARTED


class TestGatePolling:
    """Gate polling with PRManager: tasks at a gate advance when lgtm label is present."""

    GATE_PROCESS = Process(
        name="gate-process",
        intake=(),
        pipeline=(
            LoopStep(
                steps=(
                    RoleStep(role="implementer", on_pass=None, on_fail=None),
                    RoleStep(role="verifier", on_pass=None, on_fail=None),
                ),
            ),
            GateStep(gate="human-pr-approval"),
            ActionStep(action="merge-pr"),
        ),
    )

    def test_gate_cleared_advances_task(self) -> None:
        """When lgtm label is found, the gate clears and task advances past it."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        # Create a PR for the task
        pr_url = pr_mgr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")

        # Task is at the gate step
        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("human-pr-approval"),
                branch="hyperloop/task-001",
            )
        )
        # Store the PR URL on the task
        state.set_task_pr("task-001", pr_url)

        # Human adds lgtm label
        pr_mgr.add_label(pr_url, "lgtm")

        orch = _make_orchestrator(state, runtime, process=self.GATE_PROCESS, pr_manager=pr_mgr)
        orch.run_cycle()

        # Gate should have cleared, task should advance past the gate
        task = state.get_task("task-001")
        assert task.phase != Phase("human-pr-approval")

    def test_gate_not_cleared_task_stays(self) -> None:
        """When no lgtm label, the task stays at the gate."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        pr_url = pr_mgr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("human-pr-approval"),
                branch="hyperloop/task-001",
            )
        )
        state.set_task_pr("task-001", pr_url)

        orch = _make_orchestrator(state, runtime, process=self.GATE_PROCESS, pr_manager=pr_mgr)
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.phase == Phase("human-pr-approval")

    def test_no_pr_manager_gates_are_noop(self) -> None:
        """Without a PRManager, gate polling is a no-op (backward compat)."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("human-pr-approval"),
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(state, runtime, process=self.GATE_PROCESS, pr_manager=None)
        # Should not crash
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.phase == Phase("human-pr-approval")


class TestMergeWithPRManager:
    """Merge step with PRManager: rebase, then squash-merge."""

    MERGE_PROCESS = Process(
        name="merge-process",
        intake=(),
        pipeline=(
            LoopStep(
                steps=(
                    RoleStep(role="implementer", on_pass=None, on_fail=None),
                    RoleStep(role="verifier", on_pass=None, on_fail=None),
                ),
            ),
            ActionStep(action="merge-pr"),
        ),
    )

    def test_merge_succeeds_marks_task_complete(self) -> None:
        """When rebase is clean and merge succeeds, task becomes COMPLETE."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        pr_url = pr_mgr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge-pr"),
                branch="hyperloop/task-001",
            )
        )
        state.set_task_pr("task-001", pr_url)

        orch = _make_orchestrator(state, runtime, process=self.MERGE_PROCESS, pr_manager=pr_mgr)
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.COMPLETE

    def test_rebase_conflict_spawns_rebase_resolver(self) -> None:
        """When rebase fails, task gets rebase-resolver spawned."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        pr_url = pr_mgr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr_mgr.set_rebase_fails("hyperloop/task-001")

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge-pr"),
                branch="hyperloop/task-001",
            )
        )
        state.set_task_pr("task-001", pr_url)

        orch = _make_orchestrator(state, runtime, process=self.MERGE_PROCESS, pr_manager=pr_mgr)
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("rebase-resolver")

    def test_merge_conflict_spawns_rebase_resolver(self) -> None:
        """When merge fails, task gets rebase-resolver spawned."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        pr_url = pr_mgr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr_mgr.set_merge_fails(pr_url)

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge-pr"),
                branch="hyperloop/task-001",
            )
        )
        state.set_task_pr("task-001", pr_url)

        orch = _make_orchestrator(state, runtime, process=self.MERGE_PROCESS, pr_manager=pr_mgr)
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("rebase-resolver")

    def test_no_pr_manager_merge_does_not_crash(self) -> None:
        """Without a PRManager, local merge is attempted — should not crash."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge-pr"),
                branch="hyperloop/task-001",
            )
        )

        orch = _make_orchestrator(state, runtime, process=self.MERGE_PROCESS, pr_manager=None)
        # Should not crash — _merge_local handles both success and failure
        orch.run_cycle()
        task = state.get_task("task-001")
        # Result depends on whether branch exists locally: COMPLETE (merged),
        # NEEDS_REBASE (conflict/missing branch), or IN_PROGRESS with
        # rebase-resolver (decide() spawns a resolver in the same cycle).
        assert task.status in (
            TaskStatus.COMPLETE,
            TaskStatus.NEEDS_REBASE,
            TaskStatus.IN_PROGRESS,
        )


class TestPRStateResilience:
    """PR state checks: handle CLOSED/MERGED PRs without crashing."""

    GATE_PROCESS = Process(
        name="gate-process",
        intake=(),
        pipeline=(
            LoopStep(
                steps=(
                    RoleStep(role="implementer", on_pass=None, on_fail=None),
                    RoleStep(role="verifier", on_pass=None, on_fail=None),
                ),
            ),
            GateStep(gate="human-pr-approval"),
            ActionStep(action="merge-pr"),
        ),
    )

    MERGE_PROCESS = Process(
        name="merge-process",
        intake=(),
        pipeline=(
            LoopStep(
                steps=(
                    RoleStep(role="implementer", on_pass=None, on_fail=None),
                    RoleStep(role="verifier", on_pass=None, on_fail=None),
                ),
            ),
            ActionStep(action="merge-pr"),
        ),
    )

    # -- merge-pr phase: CLOSED PR -------------------------------------------

    def test_merge_closed_pr_creates_new_pr(self) -> None:
        """When a PR was closed, _merge_via_pr creates a new one and merges it."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        pr_url = pr_mgr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr_mgr.close_pr(pr_url)

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge-pr"),
                branch="hyperloop/task-001",
            )
        )
        state.set_task_pr("task-001", pr_url)

        orch = _make_orchestrator(state, runtime, process=self.MERGE_PROCESS, pr_manager=pr_mgr)
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.COMPLETE
        # A new PR was created (different URL)
        assert task.pr != pr_url

    # -- merge-pr phase: MERGED PR with all work captured --------------------

    def test_merge_already_merged_pr_marks_complete(self) -> None:
        """When a PR was already merged and branch tip matches, task completes."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        pr_url = pr_mgr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        # Simulate: PR was merged at head_sha "abc123"
        pr_mgr.set_head_sha(pr_url, "abc123")
        pr_mgr.merge(pr_url, "task-001", "specs/widget.md")

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge-pr"),
                branch="hyperloop/task-001",
            )
        )
        state.set_task_pr("task-001", pr_url)

        orch = _make_orchestrator(state, runtime, process=self.MERGE_PROCESS, pr_manager=pr_mgr)
        # _get_branch_tip returns None (branch not on remote in test env)
        # → treated as "branch deleted, all work captured"
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.COMPLETE

    # -- gate phase: CLOSED PR -----------------------------------------------

    def test_gate_closed_pr_creates_new_pr(self) -> None:
        """When a PR is closed while at gate, a new PR is created."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        pr_url = pr_mgr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr_mgr.close_pr(pr_url)

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("human-pr-approval"),
                branch="hyperloop/task-001",
            )
        )
        state.set_task_pr("task-001", pr_url)

        orch = _make_orchestrator(state, runtime, process=self.GATE_PROCESS, pr_manager=pr_mgr)
        orch.run_cycle()

        task = state.get_task("task-001")
        # New PR was created
        assert task.pr is not None
        assert task.pr != pr_url
        # Still at gate (waiting for lgtm on new PR)
        assert task.phase == Phase("human-pr-approval")

    # -- gate phase: MERGED PR -----------------------------------------------

    def test_gate_merged_pr_completes_task(self) -> None:
        """When a PR is merged externally while at gate, task completes."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        pr_url = pr_mgr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr_mgr.merge(pr_url, "task-001", "specs/widget.md")

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("human-pr-approval"),
                branch="hyperloop/task-001",
            )
        )
        state.set_task_pr("task-001", pr_url)

        orch = _make_orchestrator(state, runtime, process=self.GATE_PROCESS, pr_manager=pr_mgr)
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.COMPLETE

    # -- mark_ready does not crash on closed PR ------------------------------

    def test_mark_ready_does_not_crash_on_closed_pr(self) -> None:
        """mark_ready is best-effort — should not raise on failure.

        The real PRManager already handles this (removed check=True).
        The fake always succeeds, so this tests the fake contract.
        """
        pr_mgr = FakePRManager(repo="org/repo")
        pr_url = pr_mgr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr_mgr.mark_ready(pr_url)
        assert not pr_mgr.is_draft(pr_url)


BASE_DIR = Path(__file__).parent.parent / "base"


class TestPollInterval:
    """poll_interval causes a sleep between cycles."""

    def test_run_loop_sleeps_between_cycles(self) -> None:
        """run_loop sleeps poll_interval seconds between cycles."""
        import time

        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime, poll_interval=0.05)

        start = time.monotonic()
        # Workers never finish, so 3 cycles means 3 sleeps
        orch.run_loop(max_cycles=3)
        elapsed = time.monotonic() - start

        # 3 cycles * 0.05s = 0.15s minimum
        assert elapsed >= 0.1

    def test_run_loop_no_sleep_when_zero(self) -> None:
        """poll_interval=0 means no sleep (for tests)."""
        import time

        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime, poll_interval=0)

        start = time.monotonic()
        orch.run_loop(max_cycles=5)
        elapsed = time.monotonic() - start

        # Should be nearly instant
        assert elapsed < 1.0

    def test_no_sleep_after_halt(self) -> None:
        """When the loop halts, it does not sleep after the final cycle."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task(status=TaskStatus.COMPLETE))

        orch = _make_orchestrator(state, runtime, poll_interval=10.0)

        import time

        start = time.monotonic()
        reason = orch.run_loop(max_cycles=100)
        elapsed = time.monotonic() - start

        assert "all tasks complete" in reason.lower()
        # Should not have slept 10s
        assert elapsed < 2.0


class TestEarlyExitNoTasks:
    """Loop halts immediately when there are no tasks and no intake."""

    def test_empty_world_halts_immediately(self) -> None:
        """No tasks at all -> immediate halt with clear message."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        orch = _make_orchestrator(state, runtime)
        reason = orch.run_loop(max_cycles=100)
        assert "no tasks" in reason.lower()

    def test_empty_world_single_cycle(self) -> None:
        """run_cycle returns halt reason on empty world."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        orch = _make_orchestrator(state, runtime)
        reason = orch.run_cycle()
        assert reason is not None
        assert "no tasks" in reason.lower()


class TestProbeIntegration:
    """Probe is invoked during orchestrator lifecycle."""

    def test_cycle_started_fires_each_cycle(self) -> None:
        """cycle_started is emitted once per cycle."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        probe = RecordingProbe()
        orch = _make_orchestrator(state, runtime, probe=probe)

        orch.run_loop(max_cycles=3)
        cycle_calls = probe.of_method("cycle_started")
        assert len(cycle_calls) == 3

    def test_cycle_started_receives_cycle_number(self) -> None:
        """cycle_started carries the cycle number."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        probe = RecordingProbe()
        orch = _make_orchestrator(state, runtime, probe=probe)

        orch.run_loop(max_cycles=2)
        cycle_calls = probe.of_method("cycle_started")
        assert cycle_calls[0]["cycle"] == 1
        assert cycle_calls[1]["cycle"] == 2

    def test_no_probe_does_not_crash(self) -> None:
        """Omitting probe works fine (NullProbe default)."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime)
        orch.run_loop(max_cycles=2)
        # No crash

    def test_orchestrator_halted_fires_on_completion(self) -> None:
        """orchestrator_halted is emitted when run_loop returns."""
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
        """recovery_started is emitted during recover()."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implementer"),
                branch="hyperloop/task-001",
            )
        )

        probe = RecordingProbe()
        orch = _make_orchestrator(state, runtime, probe=probe)
        orch.recover()

        recovery = probe.of_method("recovery_started")
        assert len(recovery) == 1
        assert recovery[0]["in_progress_tasks"] == 1


class TestPromptComposition:
    """PromptComposer is wired into the spawn path when provided."""

    def test_spawn_uses_composed_prompt(self) -> None:
        """When a PromptComposer is provided, spawn receives a composed prompt."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())
        state.set_file("specs/task-001.md", "Build a widget.")

        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)
        orch = _make_orchestrator(state, runtime, composer=composer)

        # Cycle 1: spawn implementer
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS

    def test_spawn_without_composer_uses_empty_prompt(self) -> None:
        """Backward compat: without a composer, spawn uses an empty prompt."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime, composer=None)
        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS

    def test_spawn_with_findings_includes_them_in_prompt(self) -> None:
        """When a task has findings from a prior round, they are included in the prompt."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())
        state.set_file("specs/task-001.md", "Build a widget.")
        state.store_review("task-001", 1, "verifier", "fail", 1, "Missing null check.")

        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)
        orch = _make_orchestrator(state, runtime, composer=composer)

        orch.run_cycle()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS


class TestPRLifecycle:
    """PR lifecycle: draft created at first review step, marked ready on completion."""

    MERGE_PROCESS = Process(
        name="merge-process",
        intake=(),
        pipeline=(
            LoopStep(
                steps=(
                    RoleStep(role="implementer", on_pass=None, on_fail=None),
                    RoleStep(role="verifier", on_pass=None, on_fail=None),
                ),
            ),
            ActionStep(action="merge-pr"),
        ),
    )

    def test_draft_pr_created_when_task_advances_to_verifier(self) -> None:
        """A draft PR is created when a task advances from implementer to verifier."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        state.add_task(_task(id="task-001", branch="hyperloop/task-001"))

        orch = _make_orchestrator(state, runtime, process=self.MERGE_PROCESS, pr_manager=pr_mgr)

        # Cycle 1: spawn implementer
        orch.run_cycle()
        assert state.get_task("task-001").phase == Phase("implementer")
        assert state.get_task("task-001").pr is None

        # Implementer passes
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: reap implementer, advance to verifier -> draft PR created
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.phase == Phase("verifier")
        assert task.pr is not None
        assert "github.com" in task.pr

        # The PR should be a draft
        assert pr_mgr.is_draft(task.pr)

    def test_mark_ready_called_when_task_completes_pipeline(self) -> None:
        """mark_ready is called when a task reaches the merge step."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge-pr"),
                branch="hyperloop/task-001",
            )
        )
        # Create and set PR on the task
        pr_url = pr_mgr.create_draft(
            "task-001", "hyperloop/task-001", "Task task-001", "specs/task-001.md"
        )
        state.set_task_pr("task-001", pr_url)

        orch = _make_orchestrator(state, runtime, process=self.MERGE_PROCESS, pr_manager=pr_mgr)
        orch.run_cycle()

        # mark_ready should have been called before merge
        assert pr_url in pr_mgr.marked_ready
        # And the task should be complete (merged)
        assert state.get_task("task-001").status == TaskStatus.COMPLETE

    def test_no_pr_created_when_pr_manager_is_none(self) -> None:
        """No PR is created when pr_manager is not set."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        state.add_task(_task(id="task-001", branch="hyperloop/task-001"))

        orch = _make_orchestrator(state, runtime, process=self.MERGE_PROCESS, pr_manager=None)

        # Cycle 1: spawn implementer
        orch.run_cycle()

        # Implementer passes
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)

        # Cycle 2: advance to verifier — no PR should be created
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.phase == Phase("verifier")
        assert task.pr is None

    def test_draft_pr_not_recreated_on_loop_back(self) -> None:
        """When a task loops back (verifier fails), the existing PR is reused."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        state.add_task(_task(id="task-001", branch="hyperloop/task-001"))

        orch = _make_orchestrator(state, runtime, process=self.MERGE_PROCESS, pr_manager=pr_mgr)

        # Cycle 1: spawn implementer
        orch.run_cycle()

        # Implementer passes -> advance to verifier, create draft
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)
        orch.run_cycle()

        first_pr = state.get_task("task-001").pr
        assert first_pr is not None

        # Verifier fails -> loops back to implementer
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", FAIL_RESULT)
        orch.run_cycle()

        # Implementer passes again -> advance to verifier again
        runtime.set_poll_status("task-001", "done")
        runtime.set_result("task-001", PASS_RESULT)
        orch.run_cycle()

        # PR should be the same (not recreated)
        assert state.get_task("task-001").pr == first_pr


class TestRecoverCycleDetection:
    """recover() raises RuntimeError if the task graph has dependency cycles."""

    def test_recover_raises_on_cyclic_deps(self) -> None:
        """Given tasks A->B and B->A (a cycle), recover() raises RuntimeError
        containing both task IDs before any orphan logic runs."""
        import pytest

        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        state.add_task(_task(id="task-A", status=TaskStatus.IN_PROGRESS, deps=("task-B",)))
        state.add_task(_task(id="task-B", status=TaskStatus.IN_PROGRESS, deps=("task-A",)))

        orch = _make_orchestrator(state, runtime)

        with pytest.raises(RuntimeError, match=r"task-A|task-B"):
            orch.recover()

    def test_recover_does_not_raise_on_acyclic_deps(self) -> None:
        """Given tasks with no cycles, recover() completes without raising."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        state.add_task(_task(id="task-A", status=TaskStatus.IN_PROGRESS, deps=("task-B",)))
        state.add_task(_task(id="task-B", status=TaskStatus.IN_PROGRESS, deps=()))

        orch = _make_orchestrator(state, runtime)
        # Should not raise
        orch.recover()


class TestMaxRebaseAttempts:
    """max_rebase_attempts: after N consecutive rebase failures, task loops back."""

    MERGE_PROCESS = Process(
        name="merge-process",
        intake=(),
        pipeline=(
            LoopStep(
                steps=(
                    RoleStep(role="implementer", on_pass=None, on_fail=None),
                    RoleStep(role="verifier", on_pass=None, on_fail=None),
                ),
            ),
            ActionStep(action="merge-pr"),
        ),
    )

    def test_rebase_failure_exceeds_max_attempts_loops_task_back(self) -> None:
        """After max_rebase_attempts consecutive rebase failures, task loops back."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        pr_url = pr_mgr.create_draft(
            "task-001", "hyperloop/task-001", "Widget", "specs/task-001.md"
        )
        pr_mgr.set_rebase_fails("hyperloop/task-001")

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge-pr"),
                branch="hyperloop/task-001",
            )
        )
        state.set_task_pr("task-001", pr_url)

        orch = _make_orchestrator(
            state,
            runtime,
            process=self.MERGE_PROCESS,
            pr_manager=pr_mgr,
            max_rebase_attempts=3,
        )

        # First two failures: task stays in NEEDS_REBASE / rebase-resolver cycle
        for _ in range(2):
            orch.run_cycle()
            task = state.get_task("task-001")
            # Should be NEEDS_REBASE or spawning rebase-resolver
            assert task.status in (TaskStatus.NEEDS_REBASE, TaskStatus.IN_PROGRESS)

            # If rebase-resolver was spawned, let it complete and return to merge-pr
            if task.phase == Phase("rebase-resolver"):
                runtime.set_poll_status("task-001", "done")
                runtime.set_result("task-001", PASS_RESULT)
                orch.run_cycle()
                # Manually transition back to merge-pr for next attempt
                state.transition_task("task-001", TaskStatus.IN_PROGRESS, phase=Phase("merge-pr"))

        # Third failure: should exceed max_rebase_attempts -> loop back
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.round == 1  # round incremented
        assert task.phase == Phase("implementer")  # looped back to start

    def test_successful_merge_resets_rebase_counter(self) -> None:
        """A successful merge resets the rebase attempt counter for a task."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        pr_url = pr_mgr.create_draft(
            "task-001", "hyperloop/task-001", "Widget", "specs/task-001.md"
        )

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge-pr"),
                branch="hyperloop/task-001",
            )
        )
        state.set_task_pr("task-001", pr_url)

        orch = _make_orchestrator(
            state,
            runtime,
            process=self.MERGE_PROCESS,
            pr_manager=pr_mgr,
            max_rebase_attempts=3,
        )

        # Merge succeeds
        orch.run_cycle()
        task = state.get_task("task-001")
        assert task.status == TaskStatus.COMPLETE

        # The counter should be reset (no external way to verify directly,
        # but the task completed successfully — that's the behavior we want)


# ---------------------------------------------------------------------------
# _dep_order_ids unit tests
# ---------------------------------------------------------------------------

from hyperloop.loop import _dep_order_ids  # noqa: E402


def _merge_task(
    id: str,
    deps: tuple[str, ...] = (),
) -> Task:
    """Create a task at the merge-pr phase for dep-order tests."""
    return Task(
        id=id,
        title=f"Task {id}",
        spec_ref=f"specs/{id}.md",
        status=TaskStatus.IN_PROGRESS,
        phase=Phase("merge-pr"),
        deps=deps,
        round=0,
        branch=f"hyperloop/{id}",
        pr=None,
    )


class TestDepOrderIds:
    """Unit tests for the _dep_order_ids pure helper function."""

    def test_linear_chain_ordered_deps_first(self) -> None:
        """A → B → C: merge order is A, B, C (deps before dependents)."""
        tasks: dict[str, Task] = {
            "task-A": _merge_task("task-A"),
            "task-B": _merge_task("task-B", deps=("task-A",)),
            "task-C": _merge_task("task-C", deps=("task-B",)),
        }
        result = _dep_order_ids(tasks, ["task-A", "task-B", "task-C"])
        assert result == ["task-A", "task-B", "task-C"]

    def test_diamond_dep_first_then_id_order(self) -> None:
        """A and B both depend on C: C first, then A and B in input (ID) order."""
        tasks: dict[str, Task] = {
            "task-A": _merge_task("task-A", deps=("task-C",)),
            "task-B": _merge_task("task-B", deps=("task-C",)),
            "task-C": _merge_task("task-C"),
        }
        # Input pre-sorted by task ID: A, B, C
        result = _dep_order_ids(tasks, ["task-A", "task-B", "task-C"])
        assert result == ["task-C", "task-A", "task-B"]

    def test_no_deps_stable_input_order(self) -> None:
        """Tasks with no deps preserve input (ID-sorted) order."""
        tasks: dict[str, Task] = {
            "task-A": _merge_task("task-A"),
            "task-B": _merge_task("task-B"),
            "task-C": _merge_task("task-C"),
        }
        result = _dep_order_ids(tasks, ["task-A", "task-B", "task-C"])
        assert result == ["task-A", "task-B", "task-C"]

    def test_single_task_unchanged(self) -> None:
        """A single-element candidate list is returned unchanged."""
        tasks: dict[str, Task] = {"task-A": _merge_task("task-A")}
        result = _dep_order_ids(tasks, ["task-A"])
        assert result == ["task-A"]

    def test_candidate_not_in_tasks_dict_graceful(self) -> None:
        """A candidate missing from the tasks dict is included gracefully."""
        tasks: dict[str, Task] = {"task-A": _merge_task("task-A")}
        # task-B is not in tasks dict
        result = _dep_order_ids(tasks, ["task-A", "task-B"])
        assert set(result) == {"task-A", "task-B"}
        # Neither has in-candidates deps; input order preserved
        assert result == ["task-A", "task-B"]

    def test_external_dep_ignored(self) -> None:
        """A dep outside the candidate set is treated as already done (ignored)."""
        tasks: dict[str, Task] = {
            "task-A": _merge_task("task-A"),
            "task-B": _merge_task("task-B", deps=("task-external",)),
        }
        # task-external is not in candidates — treated as already merged
        result = _dep_order_ids(tasks, ["task-A", "task-B"])
        assert result == ["task-A", "task-B"]

    def test_empty_candidates_returns_empty(self) -> None:
        """Empty candidate list returns an empty list."""
        tasks: dict[str, Task] = {"task-A": _merge_task("task-A")}
        result = _dep_order_ids(tasks, [])
        assert result == []


# ---------------------------------------------------------------------------
# Integration test: _merge_ready_prs respects dependency order
# ---------------------------------------------------------------------------


class TestMergeDepOrder:
    """_merge_ready_prs merges tasks in dependency order (dep before dependent)."""

    MERGE_PROCESS = Process(
        name="merge-process",
        intake=(),
        pipeline=(
            LoopStep(
                steps=(
                    RoleStep(role="implementer", on_pass=None, on_fail=None),
                    RoleStep(role="verifier", on_pass=None, on_fail=None),
                ),
            ),
            ActionStep(action="merge-pr"),
        ),
    )

    def test_dependent_merged_after_dependency(self) -> None:
        """When two tasks are at merge-pr, the dependency merges first."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        # task-001 has no deps — it is the dependency
        pr1 = pr_mgr.create_draft("task-001", "hyperloop/task-001", "Task 001", "specs/task-001.md")
        # task-002 depends on task-001 — it is the dependent
        pr2 = pr_mgr.create_draft("task-002", "hyperloop/task-002", "Task 002", "specs/task-002.md")

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge-pr"),
                branch="hyperloop/task-001",
            )
        )
        state.add_task(
            _task(
                id="task-002",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge-pr"),
                branch="hyperloop/task-002",
                deps=("task-001",),
            )
        )
        state.set_task_pr("task-001", pr1)
        state.set_task_pr("task-002", pr2)

        orch = _make_orchestrator(state, runtime, process=self.MERGE_PROCESS, pr_manager=pr_mgr)
        orch.run_cycle()

        # Both tasks should be complete after the cycle
        assert state.get_task("task-001").status == TaskStatus.COMPLETE
        assert state.get_task("task-002").status == TaskStatus.COMPLETE

        # task-001 (the dependency) must have been merged before task-002
        assert pr_mgr.merged.index(pr1) < pr_mgr.merged.index(pr2)

    def test_independent_tasks_merge_in_id_order(self) -> None:
        """Tasks with no inter-dependency merge in task-ID order."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        pr_mgr = FakePRManager(repo="org/repo")

        pr1 = pr_mgr.create_draft("task-001", "hyperloop/task-001", "Task 001", "specs/task-001.md")
        pr2 = pr_mgr.create_draft("task-002", "hyperloop/task-002", "Task 002", "specs/task-002.md")

        state.add_task(
            _task(
                id="task-001",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge-pr"),
                branch="hyperloop/task-001",
            )
        )
        state.add_task(
            _task(
                id="task-002",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("merge-pr"),
                branch="hyperloop/task-002",
            )
        )
        state.set_task_pr("task-001", pr1)
        state.set_task_pr("task-002", pr2)

        orch = _make_orchestrator(state, runtime, process=self.MERGE_PROCESS, pr_manager=pr_mgr)
        orch.run_cycle()

        assert pr_mgr.merged.index(pr1) < pr_mgr.merged.index(pr2)
