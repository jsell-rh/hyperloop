"""TmuxRuntime — spawns workers as tmux windows in git worktrees.

Uses tmux to run worker agents in named windows within a shared session.
Each worker gets its own worktree and tmux window, allowing the user to
attach and observe agents working in real time.

The tmux session is named after the repo (e.g. ``hyperloop-myproject``)
and created detached. To observe workers:

    tmux attach -t hyperloop-myproject

Individual workers run in named windows (e.g. ``hyperloop-myproject:task-001``).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from hyperloop.adapters.runtime._worktree import (
    clean_git_env,
    cleanup_worktree,
    create_worktree,
    delete_branch,
    ensure_worktrees_gitignored,
    get_worktree_branch,
    read_result,
)
from hyperloop.domain.model import WorkerHandle, WorkerResult

if TYPE_CHECKING:
    from hyperloop.ports.runtime import WorkerPollStatus

log: structlog.stdlib.BoundLogger = structlog.get_logger()


class TmuxRuntime:
    """Runtime implementation using tmux windows in git worktrees.

    All workers share a single tmux session named after the repo
    (e.g. ``hyperloop-myproject``).  Each worker gets its own named
    window within that session.
    """

    def __init__(
        self,
        repo_path: str,
        worktree_base: str | None = None,
        command: str | None = None,
        session: str | None = None,
    ) -> None:
        self._repo_path = repo_path
        self._worktree_base = worktree_base or f"{repo_path}/worktrees/workers"
        self._command = command or "claude --dangerously-skip-permissions"
        repo_name = Path(repo_path).resolve().name
        self._session = session or f"hyperloop-{repo_name}"
        self._worktrees: dict[str, str] = {}  # task_id -> worktree_path
        self._session_created = False

    def spawn(self, task_id: str, role: str, prompt: str, branch: str) -> WorkerHandle:
        """Create a worktree, tmux window, send the command, return a handle."""
        worktree_path = os.path.join(self._worktree_base, task_id)

        # Ensure the parent directory exists and is gitignored
        os.makedirs(self._worktree_base, exist_ok=True)
        ensure_worktrees_gitignored(self._repo_path)

        # Create the git worktree
        create_worktree(self._repo_path, worktree_path, branch)

        # Write the prompt file
        prompt_path = os.path.join(worktree_path, "prompt.md")
        Path(prompt_path).write_text(prompt)

        # Ensure the tmux session exists
        self._ensure_session()

        # Create a new tmux window for this worker
        subprocess.run(
            [
                "tmux",
                "new-window",
                "-t",
                self._session,
                "-n",
                task_id,
                "-c",
                worktree_path,
            ],
            check=True,
            capture_output=True,
        )

        # Set remain-on-exit so the window stays visible after the command finishes
        subprocess.run(
            [
                "tmux",
                "set-option",
                "-w",
                "-t",
                f"{self._session}:{task_id}",
                "remain-on-exit",
                "on",
            ],
            check=True,
            capture_output=True,
        )

        # Send the command to run in the window
        subprocess.run(
            [
                "tmux",
                "send-keys",
                "-t",
                f"{self._session}:{task_id}",
                f"{self._command} < prompt.md",
                "Enter",
            ],
            check=True,
            capture_output=True,
        )

        self._worktrees[task_id] = worktree_path

        attach_cmd = f"tmux attach -t {self._session}:{task_id}"
        log.info(
            "tmux_worker_spawned",
            task_id=task_id,
            role=role,
            attach=attach_cmd,
        )

        return WorkerHandle(
            task_id=task_id,
            role=role,
            agent_id=task_id,
            session_id=self._session,
        )

    def poll(self, handle: WorkerHandle) -> WorkerPollStatus:
        """Check worker status via result file and tmux window state.

        Strategy:
        1. If ``.worker-result.json`` exists in the worktree -> "done".
        2. If the tmux window is gone -> "failed" (process exited without result).
        3. Otherwise -> "running".
        """
        task_id = handle.task_id
        worktree_path = self._worktrees.get(task_id)

        if worktree_path is None:
            worktree_path = os.path.join(self._worktree_base, task_id)

        # Check for result file first
        result_path = os.path.join(worktree_path, ".worker-result.json")
        if os.path.exists(result_path):
            return "done"

        # Check if the tmux window still exists
        if not self._window_exists(task_id):
            return "failed"

        return "running"

    def reap(self, handle: WorkerHandle) -> WorkerResult:
        """Read the result file, kill the tmux window, clean up worktree.

        Preserves the branch so later pipeline steps (e.g. merge-pr) can use it.
        """
        task_id = handle.task_id
        worktree_path = self._worktrees.get(task_id)

        if worktree_path is None:
            worktree_path = os.path.join(self._worktree_base, task_id)

        result = read_result(worktree_path)

        # Kill the tmux window (best-effort, may already be gone)
        self._kill_window(task_id)

        # Clean up internal tracking and worktree
        self._worktrees.pop(task_id, None)
        cleanup_worktree(self._repo_path, worktree_path)

        return result

    def cancel(self, handle: WorkerHandle) -> None:
        """Kill the tmux window, clean up worktree and branch."""
        task_id = handle.task_id
        worktree_path = self._worktrees.get(task_id)

        if worktree_path is None:
            worktree_path = os.path.join(self._worktree_base, task_id)

        branch = get_worktree_branch(worktree_path)

        # Kill the tmux window
        self._kill_window(task_id)

        # Clean up internal tracking and worktree
        self._worktrees.pop(task_id, None)
        cleanup_worktree(self._repo_path, worktree_path)
        delete_branch(self._repo_path, branch)

    def find_orphan(self, task_id: str, branch: str) -> WorkerHandle | None:
        """Check if a worktree and tmux window exist for this task_id."""
        worktree_path = os.path.join(self._worktree_base, task_id)

        if not os.path.isdir(worktree_path):
            return None

        # Verify the worktree is on the expected branch
        try:
            result = subprocess.run(
                ["git", "-C", worktree_path, "branch", "--show-current"],
                check=True,
                capture_output=True,
                text=True,
                env=clean_git_env(),
            )
            current_branch = result.stdout.strip()
            if current_branch != branch:
                return None
        except subprocess.CalledProcessError:
            return None

        # Check if the tmux window still exists
        window_alive = self._window_exists(task_id)

        return WorkerHandle(
            task_id=task_id,
            role="unknown",
            agent_id=task_id,
            session_id=self._session if window_alive else None,
        )

    # -- Private helpers -------------------------------------------------------

    def _ensure_session(self) -> None:
        """Create the tmux session if it doesn't exist yet."""
        if self._session_created:
            return

        # Check if session already exists
        result = subprocess.run(
            ["tmux", "has-session", "-t", self._session],
            capture_output=True,
        )
        if result.returncode != 0:
            subprocess.run(
                ["tmux", "new-session", "-d", "-s", self._session],
                check=True,
                capture_output=True,
            )
        self._session_created = True

    def _window_exists(self, task_id: str) -> bool:
        """Check whether a tmux window with the given name exists in the session."""
        result = subprocess.run(
            [
                "tmux",
                "list-windows",
                "-t",
                self._session,
                "-F",
                "#{window_name}",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False

        window_names = result.stdout.strip().splitlines()
        return task_id in window_names

    def _kill_window(self, task_id: str) -> None:
        """Kill a tmux window (best-effort, ignores errors if already gone)."""
        subprocess.run(
            ["tmux", "kill-window", "-t", f"{self._session}:{task_id}"],
            capture_output=True,
        )
