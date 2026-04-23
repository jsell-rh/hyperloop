"""Shared worktree helpers for Runtime adapters.

Provides git-worktree creation, cleanup, and branch management logic
used by AgentSdkRuntime.

All functions are module-level and take ``repo_path`` as a parameter
instead of referencing ``self``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def clean_git_env() -> dict[str, str]:
    """Return a copy of the environment with interfering GIT_* variables removed.

    Git sets variables like GIT_INDEX_FILE, GIT_DIR, etc. when running hooks
    or inside worktrees. These interfere when we spawn new git operations
    targeting a different repo. Stripping them ensures each git command
    operates on the repo specified via -C.
    """
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("GIT_"):
            del env[key]
    return env


_GITIGNORE_ENTRIES = [
    "worktrees/",
    ".agent-memory/",
]


def ensure_worktrees_gitignored(repo_path: str) -> None:
    """Ensure hyperloop-managed paths are in the target repo's .gitignore.

    Adds worktrees/ (prevents worktree gitlinks from being staged) and
    .agent-memory/ (Claude agent memory, never tracked) if not present.
    """
    repo = Path(repo_path)
    gitignore = repo / ".gitignore"
    content = gitignore.read_text() if gitignore.is_file() else ""

    lines = content.splitlines()
    added = False
    for entry in _GITIGNORE_ENTRIES:
        if entry not in lines:
            if content and not content.endswith("\n"):
                content += "\n"
            content += entry + "\n"
            added = True

    if added:
        gitignore.write_text(content)


def create_worktree(repo_path: str, worktree_path: str, branch: str) -> None:
    """Create a git worktree, handling stale state from previous runs.

    Cleans up any stale worktree directory or branch before creating.
    Always prunes stale worktree references first — git's internal tracking
    can outlive the worktree directory (e.g. after a crash or manual cleanup).

    If the main repo's HEAD is on the target branch (leftover from a
    crashed run), switches the main repo back to its default branch
    to free the worker branch for the new worktree.
    """
    env = clean_git_env()

    # Prune stale worktree references whose directories no longer exist.
    # Without this, git refuses to checkout a branch it thinks is already
    # checked out by a (now-gone) worktree.
    subprocess.run(
        ["git", "-C", repo_path, "worktree", "prune"],
        capture_output=True,
        env=env,
    )

    # Clean up stale worktree directory from a previous run
    if os.path.exists(worktree_path):
        cleanup_worktree(repo_path, worktree_path)

    # If the main repo is on this branch (from a previous crash), free it
    _free_branch_from_main_repo(repo_path, branch, env)

    # Try attaching to an existing branch
    result = subprocess.run(
        ["git", "-C", repo_path, "worktree", "add", worktree_path, branch],
        capture_output=True,
        env=env,
    )
    if result.returncode == 0:
        return

    # Branch doesn't exist — create it
    create = subprocess.run(
        [
            "git",
            "-C",
            repo_path,
            "worktree",
            "add",
            worktree_path,
            "-b",
            branch,
            "HEAD",
        ],
        capture_output=True,
        env=env,
    )
    if create.returncode == 0:
        return

    # Branch name exists but isn't a worktree — force-reset and attach
    subprocess.run(
        ["git", "-C", repo_path, "branch", "-f", branch, "HEAD"],
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "-C", repo_path, "worktree", "add", worktree_path, branch],
        check=True,
        capture_output=True,
        env=env,
    )


def _free_branch_from_main_repo(repo_path: str, branch: str, env: dict[str, str]) -> None:
    """If the main repo's HEAD is on the given branch, switch away.

    This recovers from a previous crash that left the repo on a worker
    branch (e.g. old rebase_branch doing ``git checkout`` on the main repo).
    """
    current = subprocess.run(
        ["git", "-C", repo_path, "branch", "--show-current"],
        capture_output=True,
        text=True,
        env=env,
    )
    if current.stdout.strip() != branch:
        return

    # Try common default branch names
    for candidate in ("main", "master"):
        result = subprocess.run(
            ["git", "-C", repo_path, "checkout", candidate],
            capture_output=True,
            env=env,
        )
        if result.returncode == 0:
            return

    # Last resort: detach HEAD to free the branch
    subprocess.run(
        ["git", "-C", repo_path, "checkout", "--detach"],
        capture_output=True,
        env=env,
    )


def get_worktree_branch(worktree_path: str) -> str | None:
    """Get the branch name for a worktree, or None if it can't be determined."""
    if not os.path.isdir(worktree_path):
        return None

    try:
        result = subprocess.run(
            ["git", "-C", worktree_path, "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
            env=clean_git_env(),
        )
        branch = result.stdout.strip()
        return branch if branch else None
    except subprocess.CalledProcessError:
        return None


def cleanup_worktree(repo_path: str, worktree_path: str) -> None:
    """Remove the worktree directory. Does not touch internal tracking dicts."""
    if not os.path.isdir(worktree_path):
        return

    env = clean_git_env()
    try:
        subprocess.run(
            [
                "git",
                "-C",
                repo_path,
                "worktree",
                "remove",
                "--force",
                worktree_path,
            ],
            check=True,
            capture_output=True,
            env=env,
        )
    except subprocess.CalledProcessError:
        shutil.rmtree(worktree_path, ignore_errors=True)
        subprocess.run(
            ["git", "-C", repo_path, "worktree", "prune"],
            capture_output=True,
            env=env,
        )


def delete_branch(repo_path: str, branch: str | None) -> None:
    """Delete a branch from the repo (best-effort, used by cancel)."""
    if branch:
        subprocess.run(
            ["git", "-C", repo_path, "branch", "-D", branch],
            capture_output=True,
            env=clean_git_env(),
        )
