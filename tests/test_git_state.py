"""Integration tests for GitStateStore — exercises the adapter against real git repos."""

from __future__ import annotations

import subprocess
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from hyperloop.adapters.git.state import GitStateStore
from hyperloop.domain.model import Phase, TaskStatus

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_repo(path: Path) -> None:
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


TASK_027_CONTENT = dedent("""\
    ---
    id: task-027
    title: Implement Places DB persistent storage
    spec_ref: specs/persistence.md
    status: not-started
    phase: null
    deps: [task-004]
    round: 0
    branch: null
    pr: null
    ---
    """)

TASK_028_CONTENT = dedent("""\
    ---
    id: task-028
    title: Add session restore
    spec_ref: specs/session.md
    status: in-progress
    phase: implementer
    deps: [task-027]
    round: 2
    branch: hyperloop/task-028
    pr: "42"
    ---
    """)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetTask:
    def test_reads_task_from_file(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        task = store.get_task("task-027")

        assert task.id == "task-027"
        assert task.title == "Implement Places DB persistent storage"
        assert task.spec_ref == "specs/persistence.md"
        assert task.status == TaskStatus.NOT_STARTED
        assert task.phase is None
        assert task.deps == ("task-004",)
        assert task.round == 0
        assert task.branch is None
        assert task.pr is None

    def test_reads_task_with_all_fields_populated(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-028", TASK_028_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        task = store.get_task("task-028")

        assert task.id == "task-028"
        assert task.title == "Add session restore"
        assert task.spec_ref == "specs/session.md"
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("implementer")
        assert task.deps == ("task-027",)
        assert task.round == 2
        assert task.branch == "hyperloop/task-028"
        assert task.pr == "42"

    def test_raises_key_error_for_missing_task(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        store = GitStateStore(repo_path=tmp_path)

        with pytest.raises(KeyError):
            store.get_task("task-999")


class TestGetWorld:
    def test_returns_snapshot_of_all_tasks(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-027", TASK_027_CONTENT)
        _write_task_file(tmp_path, "task-028", TASK_028_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        world = store.get_world()

        assert len(world.tasks) == 2
        assert "task-027" in world.tasks
        assert "task-028" in world.tasks
        assert world.tasks["task-027"].status == TaskStatus.NOT_STARTED
        assert world.tasks["task-028"].status == TaskStatus.IN_PROGRESS
        assert world.workers == {}
        assert isinstance(world.epoch, str)
        assert len(world.epoch) > 0  # should be a git SHA

    def test_returns_empty_world_for_no_tasks(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        store = GitStateStore(repo_path=tmp_path)
        world = store.get_world()

        assert world.tasks == {}
        assert world.workers == {}


class TestTransitionTask:
    def test_updates_status_and_phase(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.transition_task("task-027", TaskStatus.IN_PROGRESS, Phase("implementer"))

        # Re-read from disk to verify persistence
        task = store.get_task("task-027")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("implementer")

    def test_updates_round_when_provided(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.transition_task("task-027", TaskStatus.IN_PROGRESS, Phase("verifier"), round=3)

        task = store.get_task("task-027")
        assert task.round == 3

    def test_preserves_other_fields(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-028", TASK_028_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.transition_task("task-028", TaskStatus.COMPLETE, None)

        task = store.get_task("task-028")
        assert task.title == "Add session restore"
        assert task.spec_ref == "specs/session.md"
        assert task.deps == ("task-027",)
        assert task.branch == "hyperloop/task-028"
        assert task.pr == "42"

    def test_clears_phase_to_null(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-028", TASK_028_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.transition_task("task-028", TaskStatus.COMPLETE, None)

        task = store.get_task("task-028")
        assert task.phase is None


class TestStoreReview:
    def test_writes_review_file_with_frontmatter(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.store_review("task-027", 0, "verifier", "fail", "Build failed: missing import.")

        review_path = tmp_path / ".hyperloop" / "state" / "reviews" / "task-027-round-0.md"
        assert review_path.exists()
        content = review_path.read_text()
        assert "task_id: task-027" in content
        assert "round: 0" in content
        assert "role: verifier" in content
        assert "verdict: fail" in content
        assert "Build failed: missing import." in content

    def test_overwrites_review_for_same_round(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.store_review("task-027", 0, "verifier", "fail", "Round 0: build failed.")
        store.store_review("task-027", 0, "verifier", "pass", "Round 0: all clear.")

        review_path = tmp_path / ".hyperloop" / "state" / "reviews" / "task-027-round-0.md"
        content = review_path.read_text()
        assert "all clear" in content
        assert "build failed" not in content

    def test_multiple_rounds_create_separate_files(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.store_review("task-027", 0, "verifier", "fail", "Round 0 findings.")
        store.store_review("task-027", 1, "verifier", "fail", "Round 1 findings.")

        assert (tmp_path / ".hyperloop" / "state" / "reviews" / "task-027-round-0.md").exists()
        assert (tmp_path / ".hyperloop" / "state" / "reviews" / "task-027-round-1.md").exists()


class TestGetFindings:
    def test_returns_detail_from_latest_review(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.store_review("task-027", 0, "verifier", "fail", "Round 0 problem.")
        store.store_review("task-027", 1, "verifier", "fail", "Round 1 problem.")

        findings = store.get_findings("task-027")
        assert findings == "Round 1 problem."

    def test_returns_empty_string_when_no_reviews(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)

        store = GitStateStore(repo_path=tmp_path)
        findings = store.get_findings("task-027")
        assert findings == ""


class TestEpoch:
    def test_get_epoch_returns_git_head(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        store = GitStateStore(repo_path=tmp_path)

        result = subprocess.run(
            ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        expected_sha = result.stdout.strip()

        epoch = store.get_epoch("head")
        assert epoch == expected_sha

    def test_set_and_get_epoch_roundtrip(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        store = GitStateStore(repo_path=tmp_path)

        store.set_epoch("intake", "abc123")
        assert store.get_epoch("intake") == "abc123"

    def test_get_epoch_returns_empty_for_unknown_key(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        store = GitStateStore(repo_path=tmp_path)

        assert store.get_epoch("nonexistent") == ""


class TestReadFile:
    def test_reads_existing_file(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "hello.txt").write_text("world")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "--no-verify", "-m", "add file"],
            check=True,
            capture_output=True,
        )

        store = GitStateStore(repo_path=tmp_path)
        assert store.read_file("hello.txt") == "world"

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        store = GitStateStore(repo_path=tmp_path)

        assert store.read_file("does-not-exist.txt") is None


class TestCommit:
    def test_creates_git_commit(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        # Make a change that needs committing
        store.transition_task("task-027", TaskStatus.IN_PROGRESS, Phase("implementer"))
        store.persist("chore: advance task-027")

        # Verify the commit was created
        result = subprocess.run(
            ["git", "-C", str(tmp_path), "log", "--oneline", "-1"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "chore: advance task-027" in result.stdout

    def test_commit_includes_changed_files(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.store_review("task-027", 0, "verifier", "fail", "Something broke.")
        store.persist("chore: store review")

        # Verify the file is in the commit
        result = subprocess.run(
            ["git", "-C", str(tmp_path), "diff", "HEAD~1", "--name-only"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert ".hyperloop/state/reviews/task-027-round-0.md" in result.stdout
