"""LocalRuntime — spawns workers as subprocesses in git worktrees.

Uses the configured command (default: ``claude --dangerously-skip-permissions``)
to run worker agents. Each worker gets its own worktree on a dedicated branch.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from k_orchestrate.domain.model import Verdict, WorkerHandle, WorkerResult

if TYPE_CHECKING:
    from k_orchestrate.ports.runtime import WorkerPollStatus


def _clean_git_env() -> dict[str, str]:
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


class LocalRuntime:
    """Runtime implementation using local git worktrees and subprocesses."""

    def __init__(
        self,
        repo_path: str,
        worktree_base: str | None = None,
        command: str | None = None,
    ) -> None:
        self._repo_path = repo_path
        self._worktree_base = worktree_base or f"{repo_path}/worktrees/workers"
        self._command = command or "claude --dangerously-skip-permissions"
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._worktrees: dict[str, str] = {}  # task_id -> worktree_path

    def spawn(self, task_id: str, role: str, prompt: str, branch: str) -> WorkerHandle:
        """Create a worktree, write the prompt, start the subprocess, return a handle."""
        worktree_path = os.path.join(self._worktree_base, task_id)

        # Ensure the parent directory exists
        os.makedirs(self._worktree_base, exist_ok=True)

        # Create the git worktree on a new branch
        subprocess.run(
            [
                "git",
                "-C",
                self._repo_path,
                "worktree",
                "add",
                worktree_path,
                "-b",
                branch,
                "HEAD",
            ],
            check=True,
            capture_output=True,
            env=_clean_git_env(),
        )

        # Write the prompt file
        prompt_path = os.path.join(worktree_path, "prompt.md")
        Path(prompt_path).write_text(prompt)

        # Start the subprocess with stdin from the prompt file
        with open(prompt_path) as prompt_file:
            proc = subprocess.Popen(
                self._command,
                shell=True,
                cwd=worktree_path,
                stdin=prompt_file,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        self._processes[task_id] = proc
        self._worktrees[task_id] = worktree_path

        return WorkerHandle(
            task_id=task_id,
            role=role,
            agent_id=str(proc.pid),
            session_id=None,
        )

    def poll(self, handle: WorkerHandle) -> WorkerPollStatus:
        """Check subprocess status. Returns 'running', 'done', or 'failed'."""
        task_id = handle.task_id
        proc = self._processes.get(task_id)

        if proc is None:
            # No tracked process — check if worktree exists (orphan scenario)
            worktree_path = self._worktrees.get(task_id)
            if worktree_path and os.path.isdir(worktree_path):
                return "done"
            return "failed"

        returncode = proc.poll()

        if returncode is None:
            return "running"
        if returncode == 0:
            return "done"
        return "failed"

    def reap(self, handle: WorkerHandle) -> WorkerResult:
        """Read the result file, clean up worktree and branch, return WorkerResult."""
        task_id = handle.task_id
        worktree_path = self._worktrees.get(task_id)

        if worktree_path is None:
            worktree_path = os.path.join(self._worktree_base, task_id)

        result = self._read_result(worktree_path)
        branch = self._get_worktree_branch(worktree_path)
        self._cleanup_worktree(task_id, worktree_path, branch)

        return result

    def cancel(self, handle: WorkerHandle) -> None:
        """Kill the subprocess and clean up the worktree and branch."""
        task_id = handle.task_id
        proc = self._processes.get(task_id)

        # Kill the process if it's still running
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except (ProcessLookupError, OSError):
                pass  # Process already dead

        worktree_path = self._worktrees.get(task_id)
        if worktree_path is None:
            worktree_path = os.path.join(self._worktree_base, task_id)

        branch = self._get_worktree_branch(worktree_path)
        self._cleanup_worktree(task_id, worktree_path, branch)

    def find_orphan(self, task_id: str, branch: str) -> WorkerHandle | None:
        """Check if a worktree exists for the given branch. Return a handle if so."""
        worktree_path = os.path.join(self._worktree_base, task_id)

        if not os.path.isdir(worktree_path):
            return None

        # Verify this worktree is on the expected branch
        try:
            result = subprocess.run(
                ["git", "-C", worktree_path, "branch", "--show-current"],
                check=True,
                capture_output=True,
                text=True,
                env=_clean_git_env(),
            )
            current_branch = result.stdout.strip()
            if current_branch != branch:
                return None
        except subprocess.CalledProcessError:
            return None

        return WorkerHandle(
            task_id=task_id,
            role="unknown",
            agent_id="orphan",
            session_id=None,
        )

    # -- Private helpers -------------------------------------------------------

    def _read_result(self, worktree_path: str) -> WorkerResult:
        """Read and parse .worker-result.json from the worktree."""
        result_path = os.path.join(worktree_path, ".worker-result.json")

        if not os.path.exists(result_path):
            return WorkerResult(
                verdict=Verdict.ERROR,
                findings=0,
                detail="Worker result file not found",
            )

        try:
            with open(result_path) as f:
                data = json.load(f)
            return WorkerResult(
                verdict=Verdict(data["verdict"]),
                findings=int(data["findings"]),
                detail=str(data["detail"]),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            return WorkerResult(
                verdict=Verdict.ERROR,
                findings=0,
                detail=f"Failed to parse worker result: {exc}",
            )

    def _get_worktree_branch(self, worktree_path: str) -> str | None:
        """Get the branch name for a worktree, or None if it can't be determined."""
        if not os.path.isdir(worktree_path):
            return None

        try:
            result = subprocess.run(
                ["git", "-C", worktree_path, "branch", "--show-current"],
                check=True,
                capture_output=True,
                text=True,
                env=_clean_git_env(),
            )
            branch = result.stdout.strip()
            return branch if branch else None
        except subprocess.CalledProcessError:
            return None

    def _cleanup_worktree(self, task_id: str, worktree_path: str, branch: str | None) -> None:
        """Remove the worktree directory and delete the branch."""
        # Remove from internal tracking
        self._processes.pop(task_id, None)
        self._worktrees.pop(task_id, None)

        if not os.path.isdir(worktree_path):
            return

        # Try git worktree remove first; fall back to shutil.rmtree
        env = _clean_git_env()
        try:
            subprocess.run(
                [
                    "git",
                    "-C",
                    self._repo_path,
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
            # Force remove the directory if git worktree remove fails
            shutil.rmtree(worktree_path, ignore_errors=True)
            # Prune stale worktree references
            subprocess.run(
                ["git", "-C", self._repo_path, "worktree", "prune"],
                capture_output=True,
                env=env,
            )

        # Delete the branch
        if branch:
            subprocess.run(
                ["git", "-C", self._repo_path, "branch", "-D", branch],
                capture_output=True,
                env=env,
            )
