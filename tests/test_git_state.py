"""Integration tests for GitStateStore — exercises the adapter against real git repos.

Tests verify that state lives on the orphan `hyperloop/state` branch,
not on main. Reads use `git show`, writes buffer in memory, and
`persist()` commits to the state branch via git plumbing.
"""

from __future__ import annotations

import subprocess
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from hyperloop.adapters.git.state import GitStateStore
from hyperloop.domain.model import Phase, Task, TaskStatus

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STATE_BRANCH = "hyperloop/state"


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


def _seed_state_branch(repo: Path, task_id: str, content: str) -> None:
    """Create the state branch with a single task file committed to it.

    Uses the same plumbing approach: create orphan, write file, commit.
    """
    # Create orphan branch
    _git(repo, "checkout", "--orphan", STATE_BRANCH)
    # Remove any tracked files from index (may fail if empty, that's ok)
    subprocess.run(
        ["git", "-C", str(repo), "rm", "-rf", "--cached", "."],
        capture_output=True,
        text=True,
    )

    tasks_dir = repo / ".hyperloop" / "state" / "tasks"
    reviews_dir = repo / ".hyperloop" / "state" / "reviews"
    summaries_dir = repo / ".hyperloop" / "state" / "summaries"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    reviews_dir.mkdir(parents=True, exist_ok=True)
    summaries_dir.mkdir(parents=True, exist_ok=True)

    # Write keepfiles so empty dirs are tracked
    (reviews_dir / ".gitkeep").write_text("")
    (summaries_dir / ".gitkeep").write_text("")

    (tasks_dir / f"{task_id}.md").write_text(content)

    _git(repo, "add", ".hyperloop/")
    _git(repo, "commit", "--no-verify", "-m", f"seed {task_id}")

    # Switch back to main — clean working tree
    _git(repo, "checkout", "main")
    # Remove state files from working tree (they belong to orphan branch only)
    subprocess.run(
        ["rm", "-rf", str(repo / ".hyperloop")],
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
# Bootstrap tests
# ---------------------------------------------------------------------------


class TestBootstrap:
    def test_creates_orphan_branch_on_first_run(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        # State branch should exist
        branches = _git(tmp_path, "branch", "--list", STATE_BRANCH)
        assert STATE_BRANCH in branches

    def test_orphan_branch_has_no_shared_history_with_main(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        # Verify no common ancestor between main and state branch
        result = subprocess.run(
            ["git", "-C", str(tmp_path), "merge-base", "main", STATE_BRANCH],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0  # No common ancestor means orphan

    def test_bootstrap_creates_directory_structure(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        # Verify directories exist on state branch via git ls-tree
        tree = _git(tmp_path, "ls-tree", "-r", "--name-only", STATE_BRANCH)
        assert ".hyperloop/state/tasks/.gitkeep" in tree
        assert ".hyperloop/state/reviews/.gitkeep" in tree
        assert ".hyperloop/state/summaries/.gitkeep" in tree

    def test_bootstrap_is_idempotent(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.bootstrap()  # Should not raise

        branches = _git(tmp_path, "branch", "--list", STATE_BRANCH)
        assert STATE_BRANCH in branches

    def test_bootstrap_picks_up_existing_branch(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _seed_state_branch(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        # Should be able to read the existing task
        task = store.get_task("task-027")
        assert task.id == "task-027"

    def test_main_branch_unchanged_after_bootstrap(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        main_sha_before = _git(tmp_path, "rev-parse", "main")

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        main_sha_after = _git(tmp_path, "rev-parse", "main")
        assert main_sha_before == main_sha_after

    def test_working_tree_on_main_after_bootstrap(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        current = _git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD")
        assert current == "main"


# ---------------------------------------------------------------------------
# Read tests (git show based)
# ---------------------------------------------------------------------------


class TestGetTask:
    def test_reads_task_from_state_branch(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _seed_state_branch(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
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
        _seed_state_branch(tmp_path, "task-028", TASK_028_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
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
        store.bootstrap()

        with pytest.raises(KeyError):
            store.get_task("task-999")

    def test_reads_buffered_task_before_persist(self, tmp_path: Path) -> None:
        """Buffered writes should be visible to reads before persist."""
        _init_repo(tmp_path)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        task = Task(
            id="task-050",
            title="Buffered task",
            spec_ref="specs/buf.md",
            status=TaskStatus.NOT_STARTED,
            phase=None,
            deps=(),
            round=0,
            branch=None,
            pr=None,
        )
        store.add_task(task)

        # Should read from buffer, not yet persisted
        result = store.get_task("task-050")
        assert result.id == "task-050"


class TestGetWorld:
    def test_returns_snapshot_of_all_tasks(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _seed_state_branch(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        # Add a second task via buffer
        store.add_task(
            Task(
                id="task-028",
                title="Add session restore",
                spec_ref="specs/session.md",
                status=TaskStatus.IN_PROGRESS,
                phase=Phase("implementer"),
                deps=("task-027",),
                round=2,
                branch="hyperloop/task-028",
                pr="42",
            )
        )

        world = store.get_world()

        assert len(world.tasks) == 2
        assert "task-027" in world.tasks
        assert "task-028" in world.tasks
        assert world.tasks["task-027"].status == TaskStatus.NOT_STARTED
        assert world.tasks["task-028"].status == TaskStatus.IN_PROGRESS
        assert world.workers == {}
        assert isinstance(world.epoch, str)
        assert len(world.epoch) > 0

    def test_returns_empty_world_for_no_tasks(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        world = store.get_world()

        assert world.tasks == {}
        assert world.workers == {}


class TestTransitionTask:
    def test_updates_status_and_phase(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _seed_state_branch(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.transition_task("task-027", TaskStatus.IN_PROGRESS, Phase("implementer"))

        task = store.get_task("task-027")
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.phase == Phase("implementer")

    def test_updates_round_when_provided(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _seed_state_branch(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.transition_task("task-027", TaskStatus.IN_PROGRESS, Phase("verifier"), round=3)

        task = store.get_task("task-027")
        assert task.round == 3

    def test_preserves_other_fields(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _seed_state_branch(tmp_path, "task-028", TASK_028_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.transition_task("task-028", TaskStatus.COMPLETE, None)

        task = store.get_task("task-028")
        assert task.title == "Add session restore"
        assert task.spec_ref == "specs/session.md"
        assert task.deps == ("task-027",)
        assert task.branch == "hyperloop/task-028"
        assert task.pr == "42"

    def test_clears_phase_to_null(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _seed_state_branch(tmp_path, "task-028", TASK_028_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.transition_task("task-028", TaskStatus.COMPLETE, None)

        task = store.get_task("task-028")
        assert task.phase is None


# ---------------------------------------------------------------------------
# Review tests
# ---------------------------------------------------------------------------


class TestStoreReview:
    def test_stores_and_retrieves_review(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _seed_state_branch(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.store_review("task-027", 0, "verifier", "fail", "Build failed: missing import.")

        findings = store.get_findings("task-027")
        assert findings == "Build failed: missing import."

    def test_overwrites_review_for_same_round(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _seed_state_branch(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.store_review("task-027", 0, "verifier", "fail", "Round 0: build failed.")
        store.store_review("task-027", 0, "verifier", "pass", "Round 0: all clear.")

        findings = store.get_findings("task-027")
        assert "all clear" in findings
        assert "build failed" not in findings

    def test_multiple_rounds_get_latest(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _seed_state_branch(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.store_review("task-027", 0, "verifier", "fail", "Round 0 findings.")
        store.store_review("task-027", 1, "verifier", "fail", "Round 1 findings.")

        findings = store.get_findings("task-027")
        assert findings == "Round 1 findings."


class TestGetFindings:
    def test_returns_detail_from_latest_review(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _seed_state_branch(tmp_path, "task-027", TASK_027_CONTENT)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.store_review("task-027", 0, "verifier", "fail", "Round 0 problem.")
        store.store_review("task-027", 1, "verifier", "fail", "Round 1 problem.")

        findings = store.get_findings("task-027")
        assert findings == "Round 1 problem."

    def test_returns_empty_string_when_no_reviews(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        findings = store.get_findings("task-027")
        assert findings == ""

    def test_returns_persisted_review_after_persist(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.store_review("task-027", 0, "verifier", "fail", "Persisted finding.")
        store.persist("chore: store review")

        # Create new store instance to prove it reads from the branch
        store2 = GitStateStore(repo_path=tmp_path)
        store2.bootstrap()
        findings = store2.get_findings("task-027")
        assert findings == "Persisted finding."


# ---------------------------------------------------------------------------
# Epoch tests
# ---------------------------------------------------------------------------


class TestEpoch:
    def test_get_epoch_head_returns_main_head(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        expected_sha = _git(tmp_path, "rev-parse", "HEAD")
        epoch = store.get_epoch("head")
        assert epoch == expected_sha

    def test_set_and_get_epoch_roundtrip(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        store.set_epoch("intake", "abc123")
        assert store.get_epoch("intake") == "abc123"

    def test_get_epoch_returns_empty_for_unknown_key(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        assert store.get_epoch("nonexistent") == ""


# ---------------------------------------------------------------------------
# Read file / list files tests
# ---------------------------------------------------------------------------


class TestReadFile:
    def test_reads_existing_file_from_main(self, tmp_path: Path) -> None:
        """read_file reads from main/HEAD, not from state branch."""
        _init_repo(tmp_path)
        (tmp_path / "hello.txt").write_text("world")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "--no-verify", "-m", "add file")

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        assert store.read_file("hello.txt") == "world"

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        assert store.read_file("does-not-exist.txt") is None


class TestListFiles:
    def test_lists_files_matching_pattern(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        (specs_dir / "auth.md").write_text("# Auth")
        (specs_dir / "widget.md").write_text("# Widget")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "--no-verify", "-m", "add specs")

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        files = store.list_files("specs/*.md")
        assert "specs/auth.md" in files
        assert "specs/widget.md" in files


# ---------------------------------------------------------------------------
# Persist tests
# ---------------------------------------------------------------------------


class TestPersist:
    def test_commits_to_state_branch_not_main(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.add_task(
            Task(
                id="task-027",
                title="Implement Places DB persistent storage",
                spec_ref="specs/persistence.md",
                status=TaskStatus.NOT_STARTED,
                phase=None,
                deps=("task-004",),
                round=0,
                branch=None,
                pr=None,
            )
        )
        store.persist("chore: add task-027")

        # Verify commit on state branch
        log = _git(tmp_path, "log", "--oneline", "-1", STATE_BRANCH)
        assert "chore: add task-027" in log

    def test_main_branch_not_modified_by_persist(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        main_sha = _git(tmp_path, "rev-parse", "main")

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.add_task(
            Task(
                id="task-027",
                title="Test task",
                spec_ref="specs/test.md",
                status=TaskStatus.NOT_STARTED,
                phase=None,
                deps=(),
                round=0,
                branch=None,
                pr=None,
            )
        )
        store.persist("chore: add task")

        assert _git(tmp_path, "rev-parse", "main") == main_sha

    def test_working_tree_unaffected_by_persist(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "code.py").write_text("print('hello')")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "--no-verify", "-m", "add code")

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.add_task(
            Task(
                id="task-027",
                title="Test task",
                spec_ref="specs/test.md",
                status=TaskStatus.NOT_STARTED,
                phase=None,
                deps=(),
                round=0,
                branch=None,
                pr=None,
            )
        )
        store.persist("chore: add task")

        # Working tree should still be on main with code.py
        assert (tmp_path / "code.py").read_text() == "print('hello')"
        current = _git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD")
        assert current == "main"

    def test_persist_is_noop_with_no_changes(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        state_sha_before = _git(tmp_path, "rev-parse", STATE_BRANCH)
        store.persist("chore: no changes")
        state_sha_after = _git(tmp_path, "rev-parse", STATE_BRANCH)

        assert state_sha_before == state_sha_after

    def test_persisted_data_survives_new_store_instance(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.add_task(
            Task(
                id="task-027",
                title="Durable task",
                spec_ref="specs/durable.md",
                status=TaskStatus.NOT_STARTED,
                phase=None,
                deps=(),
                round=0,
                branch=None,
                pr=None,
            )
        )
        store.persist("chore: add task")

        # New instance should read persisted data
        store2 = GitStateStore(repo_path=tmp_path)
        store2.bootstrap()
        task = store2.get_task("task-027")
        assert task.id == "task-027"
        assert task.title == "Durable task"

    def test_persist_includes_reviews(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.store_review("task-027", 0, "verifier", "fail", "Something broke.")
        store.persist("chore: store review")

        # Verify review file on state branch
        tree = _git(tmp_path, "ls-tree", "-r", "--name-only", STATE_BRANCH)
        assert ".hyperloop/state/reviews/task-027-round-0.md" in tree


# ---------------------------------------------------------------------------
# Sync tests (basic — no remote in unit tests)
# ---------------------------------------------------------------------------


class TestSync:
    def test_sync_noop_without_remote(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)

        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()
        store.sync()  # Should not raise
