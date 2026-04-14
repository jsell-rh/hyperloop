"""Tests for the decide function — pure decision logic.

Given a World snapshot, decide() returns a list of Actions describing what
workers to reap, what tasks to spawn, and when to halt.
"""

from k_orchestrate.domain.decide import decide
from k_orchestrate.domain.model import (
    AdvanceTask,
    Halt,
    ReapWorker,
    SpawnWorker,
    Task,
    TaskStatus,
    WorkerState,
    World,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task(
    id: str = "task-001",
    status: TaskStatus = TaskStatus.NOT_STARTED,
    deps: tuple[str, ...] | None = None,
    round: int = 0,
    branch: str | None = None,
) -> Task:
    return Task(
        id=id,
        title=f"Task {id}",
        spec_ref=f"specs/{id}.md",
        status=status,
        phase=None,
        deps=deps if deps is not None else (),
        round=round,
        branch=branch,
        pr=None,
    )


def _world(
    tasks: dict[str, Task] | None = None,
    workers: dict[str, WorkerState] | None = None,
) -> World:
    return World(
        tasks=tasks or {},
        workers=workers or {},
        epoch="test-epoch",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmptyWorld:
    def test_no_tasks_no_actions(self):
        actions = decide(_world(), max_workers=4, max_rounds=50)
        assert actions == []


class TestSingleTaskSpawning:
    def test_not_started_no_deps_spawns_worker(self):
        t = _task()
        actions = decide(_world(tasks={t.id: t}), max_workers=4, max_rounds=50)
        spawns = [a for a in actions if isinstance(a, SpawnWorker)]
        assert len(spawns) == 1
        assert spawns[0].task_id == "task-001"

    def test_not_started_with_unmet_deps_no_spawn(self):
        t = _task(deps=("task-002",))
        dep = _task(id="task-002", status=TaskStatus.IN_PROGRESS, branch="worker/task-002")
        worker = WorkerState(task_id="task-002", role="implementer", status="running")
        tasks = {t.id: t, dep.id: dep}
        actions = decide(_world(tasks=tasks, workers={"w1": worker}), max_workers=4, max_rounds=50)
        spawns = [a for a in actions if isinstance(a, SpawnWorker)]
        # task-001 should not spawn because its dep (task-002) is not complete
        # task-002 should not spawn because it already has a running worker
        assert len(spawns) == 0

    def test_not_started_with_met_deps_spawns_worker(self):
        dep = _task(id="task-002", status=TaskStatus.COMPLETE)
        t = _task(deps=("task-002",))
        tasks = {t.id: t, dep.id: dep}
        actions = decide(_world(tasks=tasks), max_workers=4, max_rounds=50)
        spawns = [a for a in actions if isinstance(a, SpawnWorker)]
        assert len(spawns) == 1
        assert spawns[0].task_id == "task-001"


class TestAlreadyRunning:
    def test_in_progress_with_active_worker_no_action(self):
        t = _task(status=TaskStatus.IN_PROGRESS, branch="worker/task-001")
        worker = WorkerState(task_id="task-001", role="implementer", status="running")
        actions = decide(
            _world(tasks={t.id: t}, workers={"w1": worker}),
            max_workers=4,
            max_rounds=50,
        )
        spawns = [a for a in actions if isinstance(a, SpawnWorker)]
        reaps = [a for a in actions if isinstance(a, ReapWorker)]
        assert len(spawns) == 0
        assert len(reaps) == 0


class TestReaping:
    def test_completed_worker_pass_verdict_reaps(self):
        t = _task(status=TaskStatus.IN_PROGRESS, branch="worker/task-001")
        worker = WorkerState(task_id="task-001", role="implementer", status="done")
        actions = decide(
            _world(tasks={t.id: t}, workers={"w1": worker}),
            max_workers=4,
            max_rounds=50,
        )
        reaps = [a for a in actions if isinstance(a, ReapWorker)]
        assert len(reaps) == 1
        assert reaps[0].task_id == "task-001"

    def test_completed_worker_fail_verdict_reaps(self):
        t = _task(status=TaskStatus.IN_PROGRESS, branch="worker/task-001")
        worker = WorkerState(task_id="task-001", role="implementer", status="failed")
        actions = decide(
            _world(tasks={t.id: t}, workers={"w1": worker}),
            max_workers=4,
            max_rounds=50,
        )
        reaps = [a for a in actions if isinstance(a, ReapWorker)]
        assert len(reaps) == 1
        assert reaps[0].task_id == "task-001"


class TestConvergence:
    def test_all_complete_no_workers_halts(self):
        t1 = _task(id="task-001", status=TaskStatus.COMPLETE)
        t2 = _task(id="task-002", status=TaskStatus.COMPLETE)
        actions = decide(
            _world(tasks={t1.id: t1, t2.id: t2}),
            max_workers=4,
            max_rounds=50,
        )
        halts = [a for a in actions if isinstance(a, Halt)]
        assert len(halts) == 1
        assert "all tasks complete" in halts[0].reason.lower()


class TestMaxWorkers:
    def test_respects_max_workers_limit(self):
        tasks = {}
        for i in range(5):
            t = _task(id=f"task-{i:03d}")
            tasks[t.id] = t
        actions = decide(_world(tasks=tasks), max_workers=2, max_rounds=50)
        spawns = [a for a in actions if isinstance(a, SpawnWorker)]
        assert len(spawns) == 2

    def test_active_workers_count_against_limit(self):
        t1 = _task(id="task-001", status=TaskStatus.IN_PROGRESS, branch="worker/task-001")
        t2 = _task(id="task-002")
        t3 = _task(id="task-003")
        worker = WorkerState(task_id="task-001", role="implementer", status="running")
        actions = decide(
            _world(tasks={t1.id: t1, t2.id: t2, t3.id: t3}, workers={"w1": worker}),
            max_workers=2,
            max_rounds=50,
        )
        spawns = [a for a in actions if isinstance(a, SpawnWorker)]
        assert len(spawns) == 1


class TestPriorityOrdering:
    def test_in_progress_tasks_before_not_started(self):
        """In-progress tasks without a worker (crash recovery) should be
        prioritized over not-started tasks."""
        resuming = _task(id="task-001", status=TaskStatus.IN_PROGRESS, branch="worker/task-001")
        fresh = _task(id="task-002")
        actions = decide(
            _world(tasks={resuming.id: resuming, fresh.id: fresh}),
            max_workers=1,
            max_rounds=50,
        )
        spawns = [a for a in actions if isinstance(a, SpawnWorker)]
        assert len(spawns) == 1
        assert spawns[0].task_id == "task-001"


class TestMaxRounds:
    def test_task_at_max_rounds_advances_to_failed_and_halts(self):
        t = _task(status=TaskStatus.IN_PROGRESS, round=50, branch="worker/task-001")
        actions = decide(_world(tasks={t.id: t}), max_workers=4, max_rounds=50)
        advances = [a for a in actions if isinstance(a, AdvanceTask)]
        halts = [a for a in actions if isinstance(a, Halt)]
        assert len(advances) == 1
        assert advances[0].task_id == "task-001"
        assert advances[0].to_status == TaskStatus.FAILED
        assert len(halts) == 1
        assert "max_rounds" in halts[0].reason.lower()


class TestNeedsRebase:
    def test_needs_rebase_spawns_rebase_resolver(self):
        t = _task(status=TaskStatus.NEEDS_REBASE, branch="worker/task-001")
        actions = decide(_world(tasks={t.id: t}), max_workers=4, max_rounds=50)
        spawns = [a for a in actions if isinstance(a, SpawnWorker)]
        assert len(spawns) == 1
        assert spawns[0].task_id == "task-001"
        assert spawns[0].role == "rebase-resolver"

    def test_needs_rebase_prioritized_over_not_started(self):
        rebase = _task(id="task-001", status=TaskStatus.NEEDS_REBASE, branch="worker/task-001")
        fresh = _task(id="task-002")
        actions = decide(
            _world(tasks={rebase.id: rebase, fresh.id: fresh}),
            max_workers=1,
            max_rounds=50,
        )
        spawns = [a for a in actions if isinstance(a, SpawnWorker)]
        assert len(spawns) == 1
        assert spawns[0].task_id == "task-001"
        assert spawns[0].role == "rebase-resolver"

    def test_needs_rebase_with_active_worker_not_respawned(self):
        t = _task(status=TaskStatus.NEEDS_REBASE, branch="worker/task-001")
        worker = WorkerState(task_id="task-001", role="rebase-resolver", status="running")
        actions = decide(
            _world(tasks={t.id: t}, workers={"w1": worker}),
            max_workers=4,
            max_rounds=50,
        )
        spawns = [a for a in actions if isinstance(a, SpawnWorker)]
        assert len(spawns) == 0


class TestDependencyCycles:
    def test_deps_not_in_task_list_are_treated_as_unmet(self):
        """A dep referencing a task not in the world should be treated as unmet."""
        t = _task(deps=("task-nonexistent",))
        actions = decide(_world(tasks={t.id: t}), max_workers=4, max_rounds=50)
        spawns = [a for a in actions if isinstance(a, SpawnWorker)]
        assert len(spawns) == 0


class TestMixedScenarios:
    def test_reap_and_spawn_in_same_cycle(self):
        """Can reap a finished worker and spawn a new one in the same decide call."""
        done_task = _task(id="task-001", status=TaskStatus.IN_PROGRESS, branch="worker/task-001")
        ready_task = _task(id="task-002")
        done_worker = WorkerState(task_id="task-001", role="implementer", status="done")
        actions = decide(
            _world(
                tasks={done_task.id: done_task, ready_task.id: ready_task},
                workers={"w1": done_worker},
            ),
            max_workers=4,
            max_rounds=50,
        )
        reaps = [a for a in actions if isinstance(a, ReapWorker)]
        spawns = [a for a in actions if isinstance(a, SpawnWorker)]
        assert len(reaps) == 1
        assert reaps[0].task_id == "task-001"
        assert len(spawns) == 1
        assert spawns[0].task_id == "task-002"

    def test_reaps_come_before_spawns(self):
        """Reap actions should appear before spawn actions in the returned list."""
        done_task = _task(id="task-001", status=TaskStatus.IN_PROGRESS, branch="worker/task-001")
        ready_task = _task(id="task-002")
        done_worker = WorkerState(task_id="task-001", role="implementer", status="done")
        actions = decide(
            _world(
                tasks={done_task.id: done_task, ready_task.id: ready_task},
                workers={"w1": done_worker},
            ),
            max_workers=4,
            max_rounds=50,
        )
        reap_indices = [i for i, a in enumerate(actions) if isinstance(a, ReapWorker)]
        spawn_indices = [i for i, a in enumerate(actions) if isinstance(a, SpawnWorker)]
        if reap_indices and spawn_indices:
            assert max(reap_indices) < min(spawn_indices)

    def test_completed_and_failed_tasks_not_spawned(self):
        """Tasks that are already complete or failed should not be spawned."""
        complete = _task(id="task-001", status=TaskStatus.COMPLETE)
        failed = _task(id="task-002", status=TaskStatus.FAILED)
        ready = _task(id="task-003")
        tasks = {complete.id: complete, failed.id: failed, ready.id: ready}
        actions = decide(_world(tasks=tasks), max_workers=4, max_rounds=50)
        spawns = [a for a in actions if isinstance(a, SpawnWorker)]
        spawn_ids = {s.task_id for s in spawns}
        assert "task-001" not in spawn_ids
        assert "task-002" not in spawn_ids
        assert "task-003" in spawn_ids
