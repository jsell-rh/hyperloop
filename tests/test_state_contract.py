"""Shared contract tests for all StateStore implementations.

Every test runs against both InMemoryStateStore and GitStateStore to ensure
they implement the StateStore protocol identically.
"""

from __future__ import annotations

import subprocess
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from hyperloop.adapters.state import GitStateStore
from hyperloop.domain.model import Phase, Task, TaskStatus
from tests.fakes.state import InMemoryStateStore

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _init_git_repo(path: Path) -> None:
    """Create a git repo with an initial empty commit."""
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


def _write_task_file(repo: Path, task_id: str, content: str) -> None:
    """Write a task file into the repo's .hyperloop/state/tasks directory and commit it."""
    tasks_dir = repo / ".hyperloop" / "state" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / f"{task_id}.md").write_text(content)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--no-verify", "-m", f"add {task_id}"],
        check=True,
        capture_output=True,
    )


TASK_CONTENT = dedent("""\
    ---
    id: task-001
    title: Implement widget
    spec_ref: specs/widget.md
    status: not-started
    phase: null
    deps: [task-004]
    round: 0
    branch: null
    pr: null
    ---
    """)


def _seed_task() -> Task:
    """Return the Task domain object matching TASK_CONTENT."""
    return Task(
        id="task-001",
        title="Implement widget",
        spec_ref="specs/widget.md",
        status=TaskStatus.NOT_STARTED,
        phase=None,
        deps=("task-004",),
        round=0,
        branch=None,
        pr=None,
    )


def _make_memory_store(task: Task) -> InMemoryStateStore:
    store = InMemoryStateStore()
    store.add_task(task)
    return store


def _make_git_store(tmp_path: Path) -> GitStateStore:
    _init_git_repo(tmp_path)
    _write_task_file(tmp_path, "task-001", TASK_CONTENT)
    return GitStateStore(repo_path=tmp_path)


@pytest.fixture(params=["memory", "git"])
def state_store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> InMemoryStateStore | GitStateStore:
    """Provide both StateStore implementations for contract tests."""
    task = _seed_task()
    if request.param == "memory":
        return _make_memory_store(task)
    return _make_git_store(tmp_path)


@pytest.fixture(params=["memory", "git"])
def empty_state_store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> InMemoryStateStore | GitStateStore:
    """Provide both StateStore implementations with no tasks seeded."""
    if request.param == "memory":
        return InMemoryStateStore()
    _init_git_repo(tmp_path)
    return GitStateStore(repo_path=tmp_path)


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestGetTaskContract:
    """Store a task, retrieve it, all fields match."""

    def test_store_and_retrieve_all_fields(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        task = state_store.get_task("task-001")

        assert task.id == "task-001"
        assert task.title == "Implement widget"
        assert task.spec_ref == "specs/widget.md"
        assert task.status == TaskStatus.NOT_STARTED
        assert task.phase is None
        assert task.deps == ("task-004",)
        assert task.round == 0
        assert task.branch is None
        assert task.pr is None

    def test_get_task_raises_key_error_for_missing(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        with pytest.raises(KeyError):
            state_store.get_task("nonexistent")


class TestTransitionTaskContract:
    """Transition task status and phase."""

    def test_transition_updates_status_and_phase(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        state_store.transition_task("task-001", TaskStatus.IN_PROGRESS, Phase("implementer"))

        updated = state_store.get_task("task-001")
        assert updated.status == TaskStatus.IN_PROGRESS
        assert updated.phase == Phase("implementer")

    def test_transition_preserves_other_fields(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        state_store.transition_task("task-001", TaskStatus.IN_PROGRESS, Phase("implementer"))

        updated = state_store.get_task("task-001")
        assert updated.id == "task-001"
        assert updated.title == "Implement widget"
        assert updated.spec_ref == "specs/widget.md"
        assert updated.deps == ("task-004",)
        assert updated.round == 0

    def test_transition_clears_phase_to_none(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        state_store.transition_task("task-001", TaskStatus.IN_PROGRESS, Phase("implementer"))
        state_store.transition_task("task-001", TaskStatus.COMPLETE, None)

        updated = state_store.get_task("task-001")
        assert updated.status == TaskStatus.COMPLETE
        assert updated.phase is None

    def test_transition_updates_round(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        state_store.transition_task(
            "task-001", TaskStatus.IN_PROGRESS, Phase("implementer"), round=5
        )

        updated = state_store.get_task("task-001")
        assert updated.round == 5


class TestStoreReviewContract:
    """store_review persists a review record."""

    def test_store_review_does_not_raise(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        state_store.store_review("task-001", 1, "verifier", "fail", 1, "Test X failed.")

    def test_store_review_multiple_rounds(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        state_store.store_review("task-001", 1, "verifier", "fail", 2, "Round 1 failed.")
        state_store.store_review("task-001", 2, "verifier", "fail", 1, "Round 2 failed.")

        # get_findings returns the latest review's detail
        findings = state_store.get_findings("task-001")
        assert "Round 2 failed." in findings


class TestGetFindingsContract:
    """get_findings retrieves the latest review's detail."""

    def test_get_findings_returns_empty_when_no_reviews(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        assert state_store.get_findings("task-001") == ""

    def test_get_findings_returns_stored_detail(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        state_store.store_review("task-001", 1, "verifier", "fail", 1, "Tests failed.")
        findings = state_store.get_findings("task-001")
        assert "Tests failed." in findings

    def test_get_findings_returns_latest_review(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        state_store.store_review("task-001", 1, "verifier", "fail", 2, "Round 1 failed.")
        state_store.store_review("task-001", 2, "verifier", "fail", 1, "Round 2 failed.")
        findings = state_store.get_findings("task-001")
        assert "Round 2 failed." in findings


class TestEpochContract:
    """Epoch get/set round-trips."""

    def test_get_set_roundtrip(self, state_store: InMemoryStateStore | GitStateStore) -> None:
        state_store.set_epoch("intake", "abc123")
        assert state_store.get_epoch("intake") == "abc123"

    def test_get_returns_empty_for_unset_key(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        assert state_store.get_epoch("never-set-key") == ""

    def test_set_overwrites_previous_value(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        state_store.set_epoch("intake", "v1")
        state_store.set_epoch("intake", "v2")
        assert state_store.get_epoch("intake") == "v2"


class TestGetWorldContract:
    """get_world returns correct snapshot."""

    def test_returns_snapshot_with_seeded_task(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        world = state_store.get_world()

        assert "task-001" in world.tasks
        assert world.tasks["task-001"].id == "task-001"
        assert world.tasks["task-001"].status == TaskStatus.NOT_STARTED
        assert isinstance(world.epoch, str)

    def test_empty_world(self, empty_state_store: InMemoryStateStore | GitStateStore) -> None:
        world = empty_state_store.get_world()

        assert len(world.tasks) == 0
        assert isinstance(world.epoch, str)


class TestReadFileContract:
    """read_file returns None for missing file."""

    def test_read_missing_file_returns_none(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        assert state_store.read_file("does-not-exist.txt") is None


class TestCommitContract:
    """commit does not raise."""

    def test_commit_does_not_raise(self, state_store: InMemoryStateStore | GitStateStore) -> None:
        # Make a change first so there's something to commit (git requires it)
        state_store.transition_task("task-001", TaskStatus.IN_PROGRESS, Phase("implementer"))
        state_store.commit("chore: contract test commit")
