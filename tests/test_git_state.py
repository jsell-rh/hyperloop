"""Integration tests for GitStateStore — exercises the adapter against real git repos."""

from __future__ import annotations

import subprocess
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from hyperloop.adapters.git_state import GitStateStore
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
        ["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )


def _write_task_file(repo: Path, task_id: str, content: str) -> None:
    """Write a task file into the repo's specs/tasks directory and commit it."""
    tasks_dir = repo / "specs" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / f"{task_id}.md").write_text(content)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", f"add {task_id}"],
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

    ## Spec
    Build the Places DB schema.

    ## Findings
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
    branch: worker/task-028
    pr: "42"
    ---

    ## Spec
    Implement session restore from Places DB.

    ## Findings
    Tests failed on round 1.
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
        assert task.branch == "worker/task-028"
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
        assert task.branch == "worker/task-028"
        assert task.pr == "42"

    def test_clears_phase_to_null(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-028", TASK_028_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.transition_task("task-028", TaskStatus.COMPLETE, None)

        task = store.get_task("task-028")
        assert task.phase is None


class TestStoreFindings:
    def test_appends_findings_text(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.store_findings("task-027", "Build failed: missing import.\n")

        # Verify on disk
        content = (tmp_path / "specs" / "tasks" / "task-027.md").read_text()
        assert "Build failed: missing import." in content

    def test_appends_multiple_times(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.store_findings("task-027", "Round 1: build failed.\n")
        store.store_findings("task-027", "Round 2: tests failed.\n")

        content = (tmp_path / "specs" / "tasks" / "task-027.md").read_text()
        assert "Round 1: build failed." in content
        assert "Round 2: tests failed." in content

    def test_preserves_existing_findings(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-028", TASK_028_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.store_findings("task-028", "Round 2: new failure.\n")

        content = (tmp_path / "specs" / "tasks" / "task-028.md").read_text()
        assert "Tests failed on round 1." in content
        assert "Round 2: new failure." in content


class TestClearFindings:
    def test_clears_findings_section(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _write_task_file(tmp_path, "task-028", TASK_028_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.clear_findings("task-028")

        content = (tmp_path / "specs" / "tasks" / "task-028.md").read_text()
        # The ## Findings header should remain, but content should be empty
        assert "## Findings" in content
        assert "Tests failed on round 1." not in content


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
            ["git", "-C", str(tmp_path), "commit", "-m", "add file"],
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
        store.commit("chore: advance task-027")

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
        store.store_findings("task-027", "Something broke.\n")
        store.commit("chore: store findings")

        # Verify the file is in the commit
        result = subprocess.run(
            ["git", "-C", str(tmp_path), "diff", "HEAD~1", "--name-only"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "specs/tasks/task-027.md" in result.stdout
