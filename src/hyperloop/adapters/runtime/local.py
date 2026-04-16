"""LocalRuntime — spawns workers as subprocesses in git worktrees.

Uses the configured command (default: ``claude --dangerously-skip-permissions``)
to run worker agents. Each worker gets its own worktree on a dedicated branch.
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

logger: structlog.stdlib.BoundLogger = structlog.get_logger()

if TYPE_CHECKING:
    from hyperloop.ports.runtime import WorkerPollStatus


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

    def push_branch(self, branch: str) -> None:
        """Noop — local runtime doesn't need to push branches."""

    def spawn(self, task_id: str, role: str, prompt: str, branch: str) -> WorkerHandle:
        """Create a worktree, write the prompt, start the subprocess, return a handle."""
        worktree_path = os.path.join(self._worktree_base, task_id)

        # Ensure the parent directory exists and is gitignored
        os.makedirs(self._worktree_base, exist_ok=True)
        ensure_worktrees_gitignored(self._repo_path)

        # Create the git worktree
        create_worktree(self._repo_path, worktree_path, branch)

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
        """Read the result file, clean up worktree, return WorkerResult.

        Preserves the branch so later pipeline steps (e.g. merge-pr) can use it.
        """
        task_id = handle.task_id
        worktree_path = self._worktrees.get(task_id)

        if worktree_path is None:
            worktree_path = os.path.join(self._worktree_base, task_id)

        result = read_result(worktree_path)

        # Clean up internal tracking and worktree
        self._processes.pop(task_id, None)
        self._worktrees.pop(task_id, None)
        cleanup_worktree(self._repo_path, worktree_path)

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

        branch = get_worktree_branch(worktree_path)

        # Clean up internal tracking and worktree
        self._processes.pop(task_id, None)
        self._worktrees.pop(task_id, None)
        cleanup_worktree(self._repo_path, worktree_path)
        delete_branch(self._repo_path, branch)

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
                env=clean_git_env(),
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

    def run_serial(self, role: str, prompt: str) -> bool:
        """Run a serial agent as a subprocess on trunk. Blocks until complete."""
        logger.info("Running serial agent: %s", role)
        try:
            result = subprocess.run(
                self._command.split(),
                input=prompt,
                capture_output=True,
                text=True,
                cwd=self._repo_path,
                timeout=600,
            )
            if result.returncode != 0:
                logger.warning(
                    "Serial agent %s failed (exit %d): %s",
                    role,
                    result.returncode,
                    result.stderr[:500],
                )
                return False
            logger.info("Serial agent %s completed successfully", role)
            return True
        except subprocess.TimeoutExpired:
            logger.warning("Serial agent %s timed out after 600s", role)
            return False
