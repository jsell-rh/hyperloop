"""Repo isolation tests — verify operations don't pollute main repo state.

These tests use real git repos (via tmp_path) to catch bugs where branch
operations (rebase, merge, worktree create/cleanup) accidentally change
the main repo's HEAD, working tree, or index.

The motivating bug: PRManager.rebase_branch() was doing ``git checkout``
on the main repo, leaving it on a worker branch and causing subsequent
worktree creation to fail with "branch already used by worktree".
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from hyperloop.adapters.runtime._worktree import (
    cleanup_worktree,
    create_worktree,
)
from hyperloop.pr import PRManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in the given repo and return the result."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path, branch: str = "main") -> None:
    """Create a git repo with an initial commit on the given branch."""
    subprocess.run(
        ["git", "init", "-b", branch, str(repo)],
        check=True,
        capture_output=True,
    )
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")
    # Create an initial file so we have something to diff against
    (repo / "README.md").write_text("# Test repo\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "--no-verify", "-m", "init")


def _current_branch(repo: Path) -> str:
    """Return the current branch name of the repo."""
    result = _git(repo, "branch", "--show-current")
    return result.stdout.strip()


def _porcelain_status(repo: Path) -> str:
    """Return ``git status --porcelain`` output (empty string = clean)."""
    result = _git(repo, "status", "--porcelain")
    return result.stdout.strip()


def _create_branch_with_commit(repo: Path, branch: str, filename: str, content: str) -> None:
    """Create a branch off HEAD with a single file change and commit."""
    _git(repo, "checkout", "-b", branch)
    (repo / filename).write_text(content)
    _git(repo, "add", filename)
    _git(repo, "commit", "--no-verify", "-m", f"add {filename} on {branch}")
    _git(repo, "checkout", "-")  # return to previous branch


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRebaseBranchIsolation:
    """PRManager.rebase_branch() must not change the main repo's HEAD or
    working tree. This is the exact class of bug we previously shipped."""

    def test_rebase_branch_does_not_change_main_repo_head(self, tmp_path: Path) -> None:
        """After rebase_branch(), the main repo must still be on 'main'."""
        repo = tmp_path / "repo"
        _init_repo(repo)

        # Create a worker branch with a commit
        _create_branch_with_commit(repo, "hyperloop/task-001", "feature.py", "print('hello')\n")
        assert _current_branch(repo) == "main"

        # Add another commit on main so rebase has something to do
        (repo / "extra.txt").write_text("extra\n")
        _git(repo, "add", "extra.txt")
        _git(repo, "commit", "--no-verify", "-m", "advance main")

        pr = PRManager(repo="owner/repo")

        # Run rebase from within the repo dir (simulating orchestrator cwd)
        original_cwd = os.getcwd()
        try:
            os.chdir(str(repo))
            pr.rebase_branch("hyperloop/task-001", "main")
        finally:
            os.chdir(original_cwd)

        # The rebase itself should succeed (no remote, so push fails, but
        # the local rebase and HEAD preservation are what we're testing)
        # Note: result may be True or False depending on push outcome,
        # but HEAD must still be on main regardless.
        assert _current_branch(repo) == "main"

    def test_rebase_branch_does_not_dirty_working_tree(self, tmp_path: Path) -> None:
        """If trunk has uncommitted changes, rebase must not clobber them."""
        repo = tmp_path / "repo"
        _init_repo(repo)

        # Create a worker branch
        _create_branch_with_commit(repo, "hyperloop/task-002", "feature.py", "print('hello')\n")
        assert _current_branch(repo) == "main"

        # Create uncommitted changes on trunk (simulating state store edits)
        (repo / "dirty.txt").write_text("uncommitted state change\n")
        status_before = _porcelain_status(repo)
        assert status_before != "", "precondition: working tree should be dirty"

        pr = PRManager(repo="owner/repo")
        original_cwd = os.getcwd()
        try:
            os.chdir(str(repo))
            pr.rebase_branch("hyperloop/task-002", "main")
        finally:
            os.chdir(original_cwd)

        # HEAD must still be on main
        assert _current_branch(repo) == "main"

        # Working tree must still have exactly the same dirty files
        status_after = _porcelain_status(repo)
        assert (
            status_after == status_before
        ), f"Working tree changed!\nBefore: {status_before!r}\nAfter: {status_after!r}"

        # The dirty file content must be preserved
        assert (repo / "dirty.txt").read_text() == "uncommitted state change\n"


class TestWorktreeIsolation:
    """Worktree create/cleanup must not change the main repo's HEAD."""

    def test_create_and_cleanup_worktree_preserves_head(self, tmp_path: Path) -> None:
        """Creating and cleaning up a worktree must leave HEAD on main."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        worktree_path = str(tmp_path / "worktrees" / "task-001")
        os.makedirs(str(tmp_path / "worktrees"), exist_ok=True)

        assert _current_branch(repo) == "main"

        # Create a worktree (will create a new branch)
        create_worktree(str(repo), worktree_path, "hyperloop/task-001")

        # Main repo HEAD must not change
        assert _current_branch(repo) == "main"

        # Worktree should be on the worker branch
        wt_branch = subprocess.run(
            ["git", "-C", worktree_path, "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert wt_branch == "hyperloop/task-001"

        # Clean up the worktree
        cleanup_worktree(str(repo), worktree_path)

        # Main repo HEAD must still be on main after cleanup
        assert _current_branch(repo) == "main"

    def test_concurrent_worktrees_dont_interfere(self, tmp_path: Path) -> None:
        """Two worktrees for different branches can coexist, and cleanup of
        one does not affect the other or the main repo."""
        repo = tmp_path / "repo"
        _init_repo(repo)

        wt_base = tmp_path / "worktrees"
        os.makedirs(str(wt_base), exist_ok=True)
        wt1_path = str(wt_base / "task-001")
        wt2_path = str(wt_base / "task-002")

        # Create two worktrees
        create_worktree(str(repo), wt1_path, "hyperloop/task-001")
        create_worktree(str(repo), wt2_path, "hyperloop/task-002")

        # Both worktrees should exist and be on their respective branches
        wt1_branch = subprocess.run(
            ["git", "-C", wt1_path, "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        wt2_branch = subprocess.run(
            ["git", "-C", wt2_path, "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert wt1_branch == "hyperloop/task-001"
        assert wt2_branch == "hyperloop/task-002"

        # Main repo HEAD unchanged
        assert _current_branch(repo) == "main"

        # Make a commit in wt1 so it diverges
        (Path(wt1_path) / "wt1_file.txt").write_text("from worktree 1\n")
        subprocess.run(
            ["git", "-C", wt1_path, "add", "wt1_file.txt"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", wt1_path, "commit", "--no-verify", "-m", "wt1 commit"],
            check=True,
            capture_output=True,
        )

        # Clean up wt1 — wt2 should still be fine
        cleanup_worktree(str(repo), wt1_path)

        assert _current_branch(repo) == "main"
        assert os.path.isdir(wt2_path), "wt2 should still exist after wt1 cleanup"

        wt2_branch_after = subprocess.run(
            ["git", "-C", wt2_path, "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert wt2_branch_after == "hyperloop/task-002"

        # Clean up wt2
        cleanup_worktree(str(repo), wt2_path)
        assert _current_branch(repo) == "main"


class TestLocalMergeIsolation:
    """_merge_local must leave the repo on the base branch after merge."""

    def test_local_merge_returns_to_base_branch(self, tmp_path: Path) -> None:
        """After a successful local merge, HEAD must be on the base branch."""
        repo = tmp_path / "repo"
        _init_repo(repo)

        # Create a worker branch with a non-conflicting commit
        _create_branch_with_commit(repo, "hyperloop/task-001", "feature.py", "print('feature')\n")
        assert _current_branch(repo) == "main"

        # Set up minimal orchestrator dependencies for _merge_local
        from hyperloop.adapters.state import GitStateStore
        from hyperloop.domain.model import (
            LoopStep,
            Process,
            RoleStep,
        )
        from hyperloop.loop import Orchestrator
        from tests.fakes.probe import RecordingProbe
        from tests.fakes.runtime import InMemoryRuntime

        # Write a task file so state store has something
        tasks_dir = repo / ".hyperloop" / "state" / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        (tasks_dir / "task-001.md").write_text(
            "---\n"
            "id: task-001\n"
            "title: Test merge\n"
            "spec_ref: specs/test.md\n"
            "status: in-progress\n"
            "phase: merge-pr\n"
            "deps: []\n"
            "round: 0\n"
            "branch: hyperloop/task-001\n"
            "pr: null\n"
            "---\n"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "--no-verify", "-m", "add task")

        state = GitStateStore(repo_path=repo)
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        process = Process(
            name="test",
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

        orch = Orchestrator(
            state=state,
            runtime=runtime,
            process=process,
            repo_path=str(repo),
            poll_interval=0,
            probe=probe,
        )

        # Call _merge_local directly
        orch._merge_local("task-001", "hyperloop/task-001", "specs/test.md")

        # HEAD must still be on main
        assert _current_branch(repo) == "main"

        # Working tree should be clean (merge committed)
        assert _porcelain_status(repo) == "" or "task-001" in _porcelain_status(repo)

        # The merged file should be present on main
        assert (repo / "feature.py").exists()

    def test_local_merge_conflict_returns_to_base_branch(self, tmp_path: Path) -> None:
        """After a merge conflict (aborted), HEAD must still be on the base branch."""
        repo = tmp_path / "repo"
        _init_repo(repo)

        # Create a conflicting scenario: same file changed on both branches
        _create_branch_with_commit(
            repo, "hyperloop/task-conflict", "conflict.txt", "branch version\n"
        )
        assert _current_branch(repo) == "main"

        # Make a conflicting change on main
        (repo / "conflict.txt").write_text("main version\n")
        _git(repo, "add", "conflict.txt")
        _git(repo, "commit", "--no-verify", "-m", "conflicting change on main")

        from hyperloop.adapters.state import GitStateStore
        from hyperloop.domain.model import (
            LoopStep,
            Process,
            RoleStep,
        )
        from hyperloop.loop import Orchestrator
        from tests.fakes.probe import RecordingProbe
        from tests.fakes.runtime import InMemoryRuntime

        tasks_dir = repo / ".hyperloop" / "state" / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        (tasks_dir / "task-conflict.md").write_text(
            "---\n"
            "id: task-conflict\n"
            "title: Conflicting merge\n"
            "spec_ref: specs/test.md\n"
            "status: in-progress\n"
            "phase: merge-pr\n"
            "deps: []\n"
            "round: 0\n"
            "branch: hyperloop/task-conflict\n"
            "pr: null\n"
            "---\n"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "--no-verify", "-m", "add conflict task")

        state = GitStateStore(repo_path=repo)
        runtime = InMemoryRuntime()
        probe = RecordingProbe()
        process = Process(
            name="test",
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

        orch = Orchestrator(
            state=state,
            runtime=runtime,
            process=process,
            repo_path=str(repo),
            poll_interval=0,
            probe=probe,
        )

        orch._merge_local("task-conflict", "hyperloop/task-conflict", "specs/test.md")

        # Even after a conflict + abort, HEAD must be on main
        assert _current_branch(repo) == "main"

        # The merge itself was aborted cleanly — only the task file was
        # modified by transition_task (NEEDS_REBASE), which is expected
        # state-store behaviour, not merge pollution.
        status = _porcelain_status(repo)
        if status:
            # Only the task file should show as modified (state transition)
            modified_files = {line.lstrip().split(maxsplit=1)[1] for line in status.splitlines()}
            for f in modified_files:
                assert "task-conflict" in f, f"Unexpected dirty file after merge abort: {f}"
