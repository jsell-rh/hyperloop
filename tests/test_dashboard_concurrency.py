"""Dashboard + Orchestrator concurrent writes tests.

Verifies that dashboard control operations (restart, retire, force-clear)
survive orchestrator persist cycles when using REAL git repos with
GitStateStore. These tests exercise the actual git plumbing -- persist()
uses read-tree to pick up intervening commits from the other writer.

Uses tmp_path git repos, NOT InMemoryStateStore. No mocks.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from hyperloop.adapters.git.state import GitStateStore
from hyperloop.domain.model import Phase, Task, TaskStatus

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_repo(path: Path) -> None:
    """Create a git repo with an initial empty commit on main."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "--no-verify", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )


def _make_task(
    task_id: str,
    title: str = "Test task",
    status: TaskStatus = TaskStatus.NOT_STARTED,
    phase: Phase | None = None,
    round: int = 0,
    branch: str | None = None,
) -> Task:
    return Task(
        id=task_id,
        title=title,
        spec_ref="specs/test.md",
        status=status,
        phase=phase,
        deps=(),
        round=round,
        branch=branch,
        pr=None,
    )


# ---------------------------------------------------------------------------
# Test 1: Dashboard restart survives orchestrator persist
# ---------------------------------------------------------------------------


class TestDashboardRestartSurvivesOrchestratorPersist:
    """Dashboard restarts a task (reset phase, increment round) between
    orchestrator persist cycles. The orchestrator's next persist picks up
    the dashboard's change via read-tree."""

    def test_dashboard_restart_survives_orchestrator_persist(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)

        # Orchestrator store: add two tasks and persist
        orch_store = GitStateStore(repo_path=repo)
        orch_store.add_task(
            _make_task(
                "task-001",
                title="First task",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("verify"),
                round=2,
                branch="hyperloop/task-001",
            )
        )
        orch_store.add_task(
            _make_task(
                "task-002",
                title="Second task",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implement"),
                round=0,
                branch="hyperloop/task-002",
            )
        )
        orch_store.persist("orch: seed tasks")

        # Dashboard store (separate instance): restart task-001
        dash_store = GitStateStore(repo_path=repo)
        dash_store.transition_task(
            "task-001",
            TaskStatus.IN_PROGRESS,
            Phase("implement"),
            round=3,
        )
        dash_store.persist("dashboard: restart task-001")

        # Orchestrator: transition a DIFFERENT task (task-002)
        orch_store.transition_task(
            "task-002",
            TaskStatus.IN_PROGRESS,
            Phase("verify"),
            round=1,
        )
        orch_store.persist("orch: advance task-002")

        # Read the world -- both changes should be present
        final_store = GitStateStore(repo_path=repo)
        world = final_store.get_world()

        # Dashboard's restart change survived
        task_001 = world.tasks["task-001"]
        assert task_001.round == 3
        assert task_001.phase == Phase("implement")
        assert task_001.status == TaskStatus.IN_PROGRESS

        # Orchestrator's advance of task-002 also survived
        task_002 = world.tasks["task-002"]
        assert task_002.phase == Phase("verify")
        assert task_002.round == 1


# ---------------------------------------------------------------------------
# Test 2: Dashboard retire survives orchestrator persist
# ---------------------------------------------------------------------------


class TestDashboardRetireSurvivesOrchestratorPersist:
    """Dashboard retires a task (status=FAILED). Orchestrator transitions a
    different task. Both changes survive."""

    def test_dashboard_retire_survives_orchestrator_persist(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)

        # Seed tasks
        seed_store = GitStateStore(repo_path=repo)
        seed_store.add_task(
            _make_task(
                "task-001",
                title="To be retired",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implement"),
                round=1,
                branch="hyperloop/task-001",
            )
        )
        seed_store.add_task(
            _make_task(
                "task-002",
                title="To be advanced",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implement"),
                round=0,
                branch="hyperloop/task-002",
            )
        )
        seed_store.persist("seed tasks")

        # Dashboard retires task-001
        dash_store = GitStateStore(repo_path=repo)
        dash_store.transition_task("task-001", TaskStatus.FAILED, phase=None)
        dash_store.persist("dashboard: retire task-001")

        # Orchestrator transitions task-002 to verify
        orch_store = GitStateStore(repo_path=repo)
        orch_store.transition_task("task-002", TaskStatus.IN_PROGRESS, Phase("verify"), round=1)
        orch_store.persist("orch: advance task-002")

        # Verify both changes present
        verify_store = GitStateStore(repo_path=repo)
        task_001 = verify_store.get_task("task-001")
        assert task_001.status == TaskStatus.FAILED

        task_002 = verify_store.get_task("task-002")
        assert task_002.phase == Phase("verify")
        assert task_002.round == 1


# ---------------------------------------------------------------------------
# Test 3: Interleaved orchestrator/dashboard writes
# ---------------------------------------------------------------------------


class TestInterleavedOrchestratorDashboardWrites:
    """Three-step interleaved write sequence: orchestrator adds a review for
    task-001, dashboard retires task-002, orchestrator transitions task-003.
    All three changes are present in the final state."""

    def test_interleaved_orchestrator_dashboard_writes(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)

        # Seed three tasks
        seed_store = GitStateStore(repo_path=repo)
        seed_store.add_task(
            _make_task(
                "task-001",
                title="Task one",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("verify"),
                round=1,
                branch="hyperloop/task-001",
            )
        )
        seed_store.add_task(
            _make_task(
                "task-002",
                title="Task two",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implement"),
                round=0,
                branch="hyperloop/task-002",
            )
        )
        seed_store.add_task(
            _make_task(
                "task-003",
                title="Task three",
                status=TaskStatus.NOT_STARTED,
            )
        )
        seed_store.persist("seed tasks")

        # Step 1: Orchestrator adds a review for task-001
        orch_store = GitStateStore(repo_path=repo)
        orch_store.store_review("task-001", 1, "verifier", "fail", "Missing error handling")
        orch_store.persist("orch: review task-001")

        # Step 2: Dashboard retires task-002
        dash_store = GitStateStore(repo_path=repo)
        dash_store.transition_task("task-002", TaskStatus.FAILED, phase=None)
        dash_store.persist("dashboard: retire task-002")

        # Step 3: Orchestrator transitions task-003
        orch_store2 = GitStateStore(repo_path=repo)
        orch_store2.transition_task("task-003", TaskStatus.IN_PROGRESS, Phase("implement"), round=0)
        orch_store2.persist("orch: start task-003")

        # Read final state -- all three changes should be present
        final_store = GitStateStore(repo_path=repo)
        world = final_store.get_world()

        # Change 1: review exists for task-001
        findings = final_store.get_findings("task-001")
        assert "Missing error handling" in findings

        # Change 2: task-002 is FAILED
        assert world.tasks["task-002"].status == TaskStatus.FAILED

        # Change 3: task-003 is IN_PROGRESS at implement
        assert world.tasks["task-003"].status == TaskStatus.IN_PROGRESS
        assert world.tasks["task-003"].phase == Phase("implement")


# ---------------------------------------------------------------------------
# Test 4: Dashboard write without sync is visible locally
# ---------------------------------------------------------------------------


class TestDashboardWriteWithoutSyncIsVisibleLocally:
    """Baseline: a single GitStateStore instance can transition, persist,
    and read back the change without any sync step."""

    def test_dashboard_write_without_sync_is_visible_locally(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)

        store = GitStateStore(repo_path=repo)
        store.add_task(
            _make_task(
                "task-001",
                title="Single instance task",
                status=TaskStatus.NOT_STARTED,
            )
        )
        store.persist("seed task-001")

        # Transition and persist
        store.transition_task("task-001", TaskStatus.IN_PROGRESS, Phase("implement"))
        store.persist("transition task-001")

        # Read back -- change should be visible
        task = store.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("implement")

        # Also visible from a fresh store instance
        store2 = GitStateStore(repo_path=repo)
        task2 = store2.get_task("task-001")
        assert task2.status == TaskStatus.IN_PROGRESS
        assert task2.phase == Phase("implement")


# ---------------------------------------------------------------------------
# Test 5: Concurrent persist does not lose data
# ---------------------------------------------------------------------------


class TestConcurrentPersistDoesNotLoseData:
    """Two GitStateStore instances each add a different task. Store A persists
    first, then Store B persists. Because persist() uses read-tree to read
    the current state branch head, Store B's commit includes Store A's task.
    Both tasks exist when read from either store."""

    def test_concurrent_persist_does_not_lose_data(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)

        # Bootstrap the state branch
        bootstrap_store = GitStateStore(repo_path=repo)
        bootstrap_store.bootstrap()

        # Store A adds task-001
        store_a = GitStateStore(repo_path=repo)
        store_a.add_task(_make_task("task-001", title="Task from Store A"))
        store_a.persist("store A: add task-001")

        # Store B adds task-002 (this persist reads the tree that includes
        # task-001 from store A's commit via read-tree STATE_BRANCH)
        store_b = GitStateStore(repo_path=repo)
        store_b.add_task(_make_task("task-002", title="Task from Store B"))
        store_b.persist("store B: add task-002")

        # Read from a fresh store -- both tasks should exist
        verify_store = GitStateStore(repo_path=repo)
        world = verify_store.get_world()
        assert "task-001" in world.tasks
        assert "task-002" in world.tasks
        assert world.tasks["task-001"].title == "Task from Store A"
        assert world.tasks["task-002"].title == "Task from Store B"
