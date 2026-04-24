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

import pytest

from hyperloop.adapters.git._worktree import (
    cleanup_worktree,
    create_worktree,
)
from hyperloop.domain.model import TaskStatus
from hyperloop.pr import PRManager

pytestmark = pytest.mark.slow


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
        assert status_after == status_before, (
            f"Working tree changed!\nBefore: {status_before!r}\nAfter: {status_after!r}"
        )

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


class TestPRMergeStepIsolation:
    """PRMergeStep handles MERGED PRs with stale branch tips correctly.

    Uses a real git repo with an origin remote so _get_branch_tip returns
    an actual SHA.  The FakePRManager simulates GitHub PR state.
    """

    def test_merged_pr_with_stale_head_creates_new_pr(self, tmp_path: Path) -> None:
        """When a PR was merged at an old commit but the branch has new work,
        a new PR is created for the remaining commits."""
        from hyperloop.adapters.step_executor.pr_merge import PRMergeStep
        from hyperloop.domain.model import (
            Phase,
            Task,
        )
        from tests.fakes.pr import FakePRManager

        # --- Set up bare origin + clone ---
        bare = tmp_path / "origin.git"
        repo = tmp_path / "clone"
        subprocess.run(
            ["git", "init", "--bare", "-b", "main", str(bare)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "clone", str(bare), str(repo)],
            check=True,
            capture_output=True,
        )
        _git(repo, "config", "user.email", "test@test.com")
        _git(repo, "config", "user.name", "Test")

        # Initial commit on main
        (repo / "README.md").write_text("# Test\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "init")
        _git(repo, "push", "origin", "main")

        # Create worker branch with a commit and push
        _git(repo, "checkout", "-b", "hyperloop/task-001")
        (repo / "feature.py").write_text("# feature\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "feat: implement feature")
        _git(repo, "push", "origin", "hyperloop/task-001")
        _git(repo, "checkout", "main")

        # --- Set up FakePRManager: PR was merged at an OLD commit ---
        pr_mgr = FakePRManager(repo="org/repo")
        pr_url = pr_mgr.create_draft(
            "task-001", "hyperloop/task-001", "Test widget", "specs/test.md"
        )
        pr_mgr.set_head_sha(pr_url, "old-sha-not-matching-branch-tip")
        pr_mgr.merge(pr_url, "task-001", "specs/test.md")

        task = Task(
            id="task-001",
            title="Test widget",
            spec_ref="specs/test.md",
            status=TaskStatus.IN_PROGRESS,
            phase=Phase("merge-pr"),
            deps=(),
            round=0,
            branch="hyperloop/task-001",
            pr=pr_url,
        )

        step = PRMergeStep(pr_mgr, repo_path=str(repo))
        result = step.execute(task, "merge-pr", {})

        # A new PR should have been created (returned in pr_url)
        assert result.pr_url is not None
        assert result.pr_url != pr_url, "Should have created a new PR for unmerged work"

    def test_merged_pr_with_matching_head_succeeds(self, tmp_path: Path) -> None:
        """When a PR was merged and the branch tip matches, action succeeds."""
        from hyperloop.adapters.step_executor.pr_merge import PRMergeStep
        from hyperloop.domain.model import (
            Phase,
            StepOutcome,
            Task,
        )
        from tests.fakes.pr import FakePRManager

        # --- Set up bare origin + clone ---
        bare = tmp_path / "origin.git"
        repo = tmp_path / "clone"
        subprocess.run(
            ["git", "init", "--bare", "-b", "main", str(bare)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "clone", str(bare), str(repo)],
            check=True,
            capture_output=True,
        )
        _git(repo, "config", "user.email", "test@test.com")
        _git(repo, "config", "user.name", "Test")

        (repo / "README.md").write_text("# Test\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "init")
        _git(repo, "push", "origin", "main")

        # Create worker branch, push, get tip
        _git(repo, "checkout", "-b", "hyperloop/task-001")
        (repo / "feature.py").write_text("# feature\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "feat: implement feature")
        _git(repo, "push", "origin", "hyperloop/task-001")
        branch_tip = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _git(repo, "checkout", "main")

        # PR was merged at the SAME commit as the branch tip
        pr_mgr = FakePRManager(repo="org/repo")
        pr_url = pr_mgr.create_draft(
            "task-001", "hyperloop/task-001", "Test widget", "specs/test.md"
        )
        pr_mgr.set_head_sha(pr_url, branch_tip)
        pr_mgr.merge(pr_url, "task-001", "specs/test.md")

        task = Task(
            id="task-001",
            title="Test widget",
            spec_ref="specs/test.md",
            status=TaskStatus.IN_PROGRESS,
            phase=Phase("merge-pr"),
            deps=(),
            round=0,
            branch="hyperloop/task-001",
            pr=pr_url,
        )

        step = PRMergeStep(pr_mgr, repo_path=str(repo))
        result = step.execute(task, "merge-pr", {})

        assert result.outcome == StepOutcome.ADVANCE


class TestRebaseAutoResolution:
    """Rebase auto-resolves conflicts on .hyperloop/state/, .agent-memory/,
    and worker-result.yaml. When resolution produces empty commits, they
    are skipped instead of aborting the rebase."""

    @staticmethod
    def _setup_remote_repo(tmp_path: Path) -> tuple[Path, Path]:
        """Create a bare remote and a local clone with initial commit."""
        bare = tmp_path / "origin.git"
        repo = tmp_path / "clone"
        subprocess.run(
            ["git", "init", "--bare", "-b", "main", str(bare)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "clone", str(bare), str(repo)],
            check=True,
            capture_output=True,
        )
        _git(repo, "config", "user.email", "test@test.com")
        _git(repo, "config", "user.name", "Test")
        (repo / "README.md").write_text("# Test\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "init")
        _git(repo, "push", "origin", "main")
        return bare, repo

    def test_state_file_conflict_auto_resolved(self, tmp_path: Path) -> None:
        """Worker branch modifies a state file that trunk also modified.
        Rebase should auto-resolve by taking trunk's version."""
        _bare, repo = self._setup_remote_repo(tmp_path)

        # Create state dir on main
        state_dir = repo / ".hyperloop" / "state" / "tasks"
        state_dir.mkdir(parents=True)
        (state_dir / "task-001.md").write_text("status: not-started\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "add state file")
        _git(repo, "push", "origin", "main")

        # Create worker branch that modifies the state file
        _git(repo, "checkout", "-b", "hyperloop/task-001")
        (state_dir / "task-001.md").write_text("status: in-progress\nphase: implementer\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "worker: update state")
        # Also add real work so the branch has non-empty content
        (repo / "feature.py").write_text("print('hello')\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "feat: add feature")
        _git(repo, "push", "origin", "hyperloop/task-001")
        _git(repo, "checkout", "main")

        # Advance main — modify the same state file (orchestrator updated it)
        (state_dir / "task-001.md").write_text("status: in-progress\nphase: verifier\nround: 2\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "orchestrator: advance task")
        _git(repo, "push", "origin", "main")

        # Rebase should succeed — state conflict auto-resolved, feature kept
        pr = PRManager(repo="org/repo")
        original_cwd = os.getcwd()
        try:
            os.chdir(str(repo))
            result = pr.rebase_branch("hyperloop/task-001", "main")
        finally:
            os.chdir(original_cwd)

        assert result is True
        assert _current_branch(repo) == "main"

    def test_agent_memory_conflict_auto_resolved(self, tmp_path: Path) -> None:
        """Worker branch modifies .agent-memory/ that trunk also modified.
        Rebase should auto-resolve by taking trunk's version."""
        _bare, repo = self._setup_remote_repo(tmp_path)

        # Create .agent-memory on main
        mem_dir = repo / ".agent-memory"
        mem_dir.mkdir()
        (mem_dir / "spec-reviewer.md").write_text("memory v1\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "add agent memory")
        _git(repo, "push", "origin", "main")

        # Worker branch modifies it
        _git(repo, "checkout", "-b", "hyperloop/task-002")
        (mem_dir / "spec-reviewer.md").write_text("memory v2 from worker\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "worker: update memory")
        (repo / "feature2.py").write_text("print('feature2')\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "feat: add feature2")
        _git(repo, "push", "origin", "hyperloop/task-002")
        _git(repo, "checkout", "main")

        # Trunk modifies the same memory file
        (mem_dir / "spec-reviewer.md").write_text("memory v3 from trunk\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "orchestrator: update memory")
        _git(repo, "push", "origin", "main")

        pr = PRManager(repo="org/repo")
        original_cwd = os.getcwd()
        try:
            os.chdir(str(repo))
            result = pr.rebase_branch("hyperloop/task-002", "main")
        finally:
            os.chdir(original_cwd)

        assert result is True

    def test_verdict_file_conflict_auto_resolved(self, tmp_path: Path) -> None:
        """Worker branch has worker-result.yaml that also appears on trunk.
        Rebase should auto-resolve by deleting it."""
        _bare, repo = self._setup_remote_repo(tmp_path)

        verdict_dir = repo / ".hyperloop"
        verdict_dir.mkdir(parents=True)

        # Trunk has the verdict file (shouldn't happen, but can via bad merge)
        (verdict_dir / "worker-result.yaml").write_text("verdict: pass\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "stale verdict on trunk")
        _git(repo, "push", "origin", "main")

        # Worker branch has a different verdict
        _git(repo, "checkout", "-b", "hyperloop/task-003")
        (verdict_dir / "worker-result.yaml").write_text("verdict: fail\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "worker: write verdict")
        (repo / "feature3.py").write_text("print('feature3')\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "feat: add feature3")
        _git(repo, "push", "origin", "hyperloop/task-003")
        _git(repo, "checkout", "main")

        # Modify trunk to force divergence
        (repo / "other.txt").write_text("trunk change\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "trunk: advance")
        _git(repo, "push", "origin", "main")

        pr = PRManager(repo="org/repo")
        original_cwd = os.getcwd()
        try:
            os.chdir(str(repo))
            result = pr.rebase_branch("hyperloop/task-003", "main")
        finally:
            os.chdir(original_cwd)

        assert result is True

    def test_multiple_auto_resolvable_conflicts_in_sequence(self, tmp_path: Path) -> None:
        """Worker branch has state + agent-memory + verdict conflicts across
        multiple commits. All should be auto-resolved, with empty commits
        skipped."""
        _bare, repo = self._setup_remote_repo(tmp_path)

        state_dir = repo / ".hyperloop" / "state" / "tasks"
        state_dir.mkdir(parents=True)
        mem_dir = repo / ".agent-memory"
        mem_dir.mkdir()

        # Set up initial tracked files on main
        (state_dir / "task-001.md").write_text("status: not-started\n")
        (mem_dir / "reviewer.md").write_text("memory v1\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "init state and memory")
        _git(repo, "push", "origin", "main")

        # Worker branch: modify state, memory, and add real work
        _git(repo, "checkout", "-b", "hyperloop/task-001")
        (state_dir / "task-001.md").write_text("status: in-progress\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "worker: update state")
        (mem_dir / "reviewer.md").write_text("memory from worker\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "worker: update memory")
        (repo / "feature.py").write_text("# real work\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "feat: implement feature")
        _git(repo, "push", "origin", "hyperloop/task-001")
        _git(repo, "checkout", "main")

        # Trunk: modify the same state and memory files
        (state_dir / "task-001.md").write_text("status: complete\nround: 5\n")
        (mem_dir / "reviewer.md").write_text("memory from trunk\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "orchestrator: advance")
        _git(repo, "push", "origin", "main")

        pr = PRManager(repo="org/repo")
        original_cwd = os.getcwd()
        try:
            os.chdir(str(repo))
            result = pr.rebase_branch("hyperloop/task-001", "main")
        finally:
            os.chdir(original_cwd)

        assert result is True

    def test_real_conflict_not_auto_resolved(self, tmp_path: Path) -> None:
        """A conflict in a non-state file (real code) should NOT be
        auto-resolved — rebase_branch returns False."""
        _bare, repo = self._setup_remote_repo(tmp_path)

        (repo / "app.py").write_text("def main():\n    pass\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "add app.py")
        _git(repo, "push", "origin", "main")

        # Worker modifies app.py
        _git(repo, "checkout", "-b", "hyperloop/task-001")
        (repo / "app.py").write_text("def main():\n    print('worker')\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "worker: modify app")
        _git(repo, "push", "origin", "hyperloop/task-001")
        _git(repo, "checkout", "main")

        # Trunk modifies the same file differently
        (repo / "app.py").write_text("def main():\n    print('trunk')\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--no-verify", "-m", "trunk: modify app")
        _git(repo, "push", "origin", "main")

        pr = PRManager(repo="org/repo")
        original_cwd = os.getcwd()
        try:
            os.chdir(str(repo))
            result = pr.rebase_branch("hyperloop/task-001", "main")
        finally:
            os.chdir(original_cwd)

        assert result is False
