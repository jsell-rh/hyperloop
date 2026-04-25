"""Tests for sync conflict resolution and dashboard coordination.

Exercises GitStateStore sync with real git repos (tmp_path based) to verify:
- Fast-forward sync when no divergence
- Conflict resolution: task files take remote, review/summary files take local
- Dashboard changes survive orchestrator persist (no race)
- Dashboard persist + sync round-trips correctly
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from hyperloop.adapters.git.state import STATE_BRANCH, GitStateStore
from hyperloop.domain.model import Phase, Task, TaskStatus

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_bare(path: Path) -> None:
    """Create a bare git repo to act as the remote."""
    subprocess.run(["git", "init", "--bare", str(path)], check=True, capture_output=True)


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


def _git(path: Path, *args: str) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _clone_repo(remote: Path, local: Path) -> None:
    """Clone a bare remote into local path."""
    subprocess.run(
        ["git", "clone", str(remote), str(local)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(local), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(local), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )


def _make_task(
    task_id: str,
    title: str = "Test task",
    status: TaskStatus = TaskStatus.NOT_STARTED,
    phase: Phase | None = None,
    round: int = 0,
) -> Task:
    return Task(
        id=task_id,
        title=title,
        spec_ref="specs/test.md",
        status=status,
        phase=phase,
        deps=(),
        round=round,
        branch=None,
        pr=None,
    )


@pytest.fixture
def remote_and_clones(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Set up a bare remote + two clones (orchestrator and dashboard).

    Both clones share the same remote, so pushing from one is visible
    after fetching from the other.
    """
    remote = tmp_path / "remote.git"
    clone_a = tmp_path / "clone_a"
    clone_b = tmp_path / "clone_b"

    _init_bare(remote)

    # Clone A: seed with an initial commit + state branch
    _clone_repo(remote, clone_a)
    store_a = GitStateStore(repo_path=clone_a)
    store_a.bootstrap()
    store_a.add_task(_make_task("task-001", "First task"))
    store_a.persist("seed task-001")
    store_a.sync()

    # Clone B
    _clone_repo(remote, clone_b)

    return remote, clone_a, clone_b


# ---------------------------------------------------------------------------
# Sync: fast-forward
# ---------------------------------------------------------------------------


class TestSyncFastForward:
    def test_sync_pushes_local_to_remote(self, remote_and_clones: tuple[Path, Path, Path]) -> None:
        """When local is ahead of remote, sync pushes successfully."""
        _remote, clone_a, clone_b = remote_and_clones

        # A adds a task and persists
        store_a = GitStateStore(repo_path=clone_a)
        store_a.add_task(_make_task("task-002", "Second task"))
        store_a.persist("add task-002")
        store_a.sync()

        # B should see task-002 after sync
        store_b = GitStateStore(repo_path=clone_b)
        store_b.sync()
        task = store_b.get_task("task-002")
        assert task.id == "task-002"
        assert task.title == "Second task"

    def test_sync_pulls_remote_changes(self, remote_and_clones: tuple[Path, Path, Path]) -> None:
        """When remote is ahead, sync pulls the changes."""
        _remote, clone_a, clone_b = remote_and_clones

        # A adds and pushes
        store_a = GitStateStore(repo_path=clone_a)
        store_a.add_task(_make_task("task-003", "Third task"))
        store_a.persist("add task-003")
        store_a.sync()

        # B syncs and reads
        store_b = GitStateStore(repo_path=clone_b)
        store_b.sync()
        world = store_b.get_world()
        assert "task-003" in world.tasks


# ---------------------------------------------------------------------------
# Sync: divergence detection and conflict resolution
# ---------------------------------------------------------------------------


class TestSyncConflictResolution:
    def test_task_file_conflict_remote_wins(
        self, remote_and_clones: tuple[Path, Path, Path]
    ) -> None:
        """When both clones modify the same task file, remote version wins."""
        _remote, clone_a, clone_b = remote_and_clones

        # B: bootstrap and modify task-001 locally (becomes "remote" relative to A)
        store_b = GitStateStore(repo_path=clone_b)
        store_b.transition_task("task-001", TaskStatus.IN_PROGRESS, Phase("implementer"), round=1)
        store_b.persist("b: advance task-001")
        store_b.sync()

        # A: modify task-001 locally (diverged from remote)
        store_a = GitStateStore(repo_path=clone_a)
        store_a.transition_task("task-001", TaskStatus.IN_PROGRESS, Phase("verifier"), round=2)
        store_a.persist("a: advance task-001")

        # A syncs -- remote (B's version) should win for task files
        store_a.sync()

        task = store_a.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("implementer")
        assert task.round == 1

    def test_review_file_conflict_local_wins(
        self, remote_and_clones: tuple[Path, Path, Path]
    ) -> None:
        """When both clones write review files, local version wins."""
        _remote, clone_a, clone_b = remote_and_clones

        # B: write a review and push
        store_b = GitStateStore(repo_path=clone_b)
        store_b.store_review("task-001", 0, "verifier", "fail", "Remote review.")
        store_b.persist("b: review task-001")
        store_b.sync()

        # A: write a different review for the same round
        store_a = GitStateStore(repo_path=clone_a)
        store_a.store_review("task-001", 0, "verifier", "pass", "Local review.")
        store_a.persist("a: review task-001")

        # A syncs -- local should win for review files
        store_a.sync()

        findings = store_a.get_findings("task-001")
        assert findings == "Local review."

    def test_summary_file_conflict_local_wins(
        self, remote_and_clones: tuple[Path, Path, Path]
    ) -> None:
        """When both clones write summary files, local version wins."""
        _remote, clone_a, clone_b = remote_and_clones

        # B: write a summary and push
        store_b = GitStateStore(repo_path=clone_b)
        store_b.store_summary("specs/test.md", "remote_summary: true\n")
        store_b.persist("b: summary")
        store_b.sync()

        # A: write a different summary
        store_a = GitStateStore(repo_path=clone_a)
        store_a.store_summary("specs/test.md", "local_summary: true\n")
        store_a.persist("a: summary")

        # A syncs -- local should win for summary files
        store_a.sync()

        summary = store_a.get_summary("specs/test.md")
        assert summary is not None
        assert "local_summary" in summary

    def test_non_conflicting_changes_merge(
        self, remote_and_clones: tuple[Path, Path, Path]
    ) -> None:
        """When clones modify different files, both changes are preserved."""
        _remote, clone_a, clone_b = remote_and_clones

        # B: add a new task and push
        store_b = GitStateStore(repo_path=clone_b)
        store_b.add_task(_make_task("task-010", "B's task"))
        store_b.persist("b: add task-010")
        store_b.sync()

        # A: add a different task locally
        store_a = GitStateStore(repo_path=clone_a)
        store_a.add_task(_make_task("task-020", "A's task"))
        store_a.persist("a: add task-020")

        # A syncs -- both tasks should exist
        store_a.sync()

        world = store_a.get_world()
        assert "task-001" in world.tasks
        assert "task-010" in world.tasks
        assert "task-020" in world.tasks


# ---------------------------------------------------------------------------
# Dashboard coordination
# ---------------------------------------------------------------------------


class TestDashboardCoordination:
    def test_dashboard_changes_survive_orchestrator_persist(self, tmp_path: Path) -> None:
        """When the dashboard commits between orchestrator persists,
        the orchestrator's read-tree picks up the dashboard's changes
        because it reads the current state branch head.

        persist() uses read-tree STATE_BRANCH which includes any commits
        that happened since the last persist (including dashboard commits).
        """
        _init_repo(tmp_path)

        # Orchestrator adds task-001
        orch_store = GitStateStore(repo_path=tmp_path)
        orch_store.add_task(_make_task("task-001", "Orchestrator task"))
        orch_store.persist("orch: add task-001")

        # Dashboard (separate instance) restarts task-001
        dash_store = GitStateStore(repo_path=tmp_path)
        dash_store.transition_task(
            "task-001", TaskStatus.IN_PROGRESS, Phase("implementer"), round=1
        )
        dash_store.persist("dashboard: restart task-001")

        # Orchestrator adds task-002 in the NEXT cycle
        orch_store.add_task(_make_task("task-002", "Another task"))
        orch_store.persist("orch: add task-002")

        # Both tasks should be present, and task-001's dashboard change survived
        world = orch_store.get_world()
        assert "task-001" in world.tasks
        assert "task-002" in world.tasks
        assert world.tasks["task-001"].status == TaskStatus.IN_PROGRESS
        assert world.tasks["task-001"].phase == Phase("implementer")

    def test_dashboard_persist_then_sync_roundtrip(
        self, remote_and_clones: tuple[Path, Path, Path]
    ) -> None:
        """Dashboard persists + syncs, orchestrator sees changes after sync."""
        _remote, clone_a, clone_b = remote_and_clones

        # Dashboard (clone_b) modifies and persists + syncs
        dash_store = GitStateStore(repo_path=clone_b)
        dash_store.transition_task(
            "task-001", TaskStatus.IN_PROGRESS, Phase("implementer"), round=1
        )
        dash_store.persist("dashboard: restart task-001")
        dash_store.sync()

        # Orchestrator (clone_a) syncs and sees dashboard change
        orch_store = GitStateStore(repo_path=clone_a)
        orch_store.sync()

        task = orch_store.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("implementer")
        assert task.round == 1

    def test_dashboard_retire_survives_orchestrator_sync(
        self, remote_and_clones: tuple[Path, Path, Path]
    ) -> None:
        """Dashboard retires a task. Orchestrator syncs and sees the retirement."""
        _remote, clone_a, clone_b = remote_and_clones

        # Orchestrator adds task-002
        orch_store = GitStateStore(repo_path=clone_a)
        orch_store.add_task(_make_task("task-002", "Second task"))
        orch_store.persist("orch: add task-002")
        orch_store.sync()

        # Dashboard retires task-001
        dash_store = GitStateStore(repo_path=clone_b)
        dash_store.sync()
        dash_store.transition_task("task-001", TaskStatus.FAILED, phase=None)
        dash_store.persist("dashboard: retire task-001")
        dash_store.sync()

        # Orchestrator syncs and sees retirement
        orch_store.sync()
        task = orch_store.get_task("task-001")
        assert task.status == TaskStatus.FAILED


# ---------------------------------------------------------------------------
# Sync edge cases
# ---------------------------------------------------------------------------


class TestSyncEdgeCases:
    def test_sync_noop_without_remote(self, tmp_path: Path) -> None:
        """Sync is a no-op when there is no remote."""
        _init_repo(tmp_path)
        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.sync()  # Should not raise

    def test_sync_no_remote_branch_pushes(self, remote_and_clones: tuple[Path, Path, Path]) -> None:
        """When remote has no state branch yet, sync pushes local."""
        remote = remote_and_clones[0]

        # Create a fresh clone with no state branch on remote
        new_clone = remote.parent / "fresh_clone"
        _clone_repo(remote, new_clone)

        # Remove the state branch from remote (simulate fresh remote)
        _git(remote, "branch", "-D", STATE_BRANCH)

        # New clone creates state branch and syncs
        store = GitStateStore(repo_path=new_clone)
        store.bootstrap()
        store.add_task(_make_task("task-fresh", "Fresh task"))
        store.persist("add fresh task")
        store.sync()

        # Remote should now have the state branch
        branches = _git(remote, "branch")
        assert STATE_BRANCH in branches

    def test_sync_in_sync_is_noop(self, remote_and_clones: tuple[Path, Path, Path]) -> None:
        """When local and remote are identical, sync pushes (fast-forward noop)."""
        _remote, clone_a, _clone_b = remote_and_clones

        store = GitStateStore(repo_path=clone_a)
        local_ref_before = _git(clone_a, "rev-parse", STATE_BRANCH)
        store.sync()
        local_ref_after = _git(clone_a, "rev-parse", STATE_BRANCH)
        assert local_ref_before == local_ref_after
