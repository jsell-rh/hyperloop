"""AgentSdkRuntime — runs workers via the Claude Agent SDK.

Uses ``claude_agent_sdk.query()`` to run agents in-process.  Each parallel
worker gets its own worktree; serial agents run on trunk.  The SDK handles
tool execution, context management, and clean exit — no subprocess polling
or result-file conventions needed.

Completion and verdict are derived from the SDK's ``ResultMessage``:
``is_error`` maps to ``Verdict.ERROR``, otherwise ``Verdict.PASS``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import glob
import os
import re
import threading
from typing import TYPE_CHECKING, cast

import structlog
import yaml

from hyperloop.adapters.runtime._worktree import (
    clean_git_env,
    cleanup_worktree,
    create_worktree,
    delete_branch,
    ensure_worktrees_gitignored,
    get_worktree_branch,
)
from hyperloop.domain.model import Verdict, WorkerHandle, WorkerResult

if TYPE_CHECKING:
    from hyperloop.ports.runtime import WorkerPollStatus

log: structlog.stdlib.BoundLogger = structlog.get_logger()


class AgentSdkRuntime:
    """Runtime implementation using the Claude Agent SDK.

    Runs agents via ``claude_agent_sdk.query()`` in a background event loop.
    Each parallel worker gets a worktree; serial agents run on trunk.
    """

    def __init__(
        self,
        repo_path: str,
        worktree_base: str | None = None,
        model: str | None = None,
    ) -> None:
        self._repo_path = repo_path
        self._worktree_base = worktree_base or f"{repo_path}/worktrees/workers"
        self._model = model
        self._worktrees: dict[str, str] = {}  # task_id -> worktree_path
        self._futures: dict[str, concurrent.futures.Future[WorkerResult]] = {}

        # Background event loop for async SDK calls
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def worker_epilogue(self) -> str:
        """Return empty string — local SDK runtime has no push requirement."""
        return ""

    def push_branch(self, branch: str) -> None:
        """Push branch to remote if one exists. Best-effort — no remote is fine."""
        import contextlib
        import subprocess

        with contextlib.suppress(subprocess.CalledProcessError):
            subprocess.run(
                ["git", "-C", self._repo_path, "push", "-u", "origin", branch],
                check=True,
                capture_output=True,
                env=clean_git_env(),
            )

    def spawn(self, task_id: str, role: str, prompt: str, branch: str) -> WorkerHandle:
        """Create a worktree and start an SDK agent session."""
        worktree_path = os.path.join(self._worktree_base, task_id)

        os.makedirs(self._worktree_base, exist_ok=True)
        ensure_worktrees_gitignored(self._repo_path)
        create_worktree(self._repo_path, worktree_path, branch)

        # Submit the agent to the background event loop
        future = asyncio.run_coroutine_threadsafe(
            self._run_agent(prompt, worktree_path), self._loop
        )
        self._futures[task_id] = future
        self._worktrees[task_id] = worktree_path

        log.info(
            "sdk_worker_spawned",
            task_id=task_id,
            role=role,
            cwd=worktree_path,
        )

        return WorkerHandle(
            task_id=task_id,
            role=role,
            agent_id=task_id,
            session_id=None,
        )

    def poll(self, handle: WorkerHandle) -> WorkerPollStatus:
        """Check if the SDK agent has completed."""
        task_id = handle.task_id
        future = self._futures.get(task_id)

        if future is None:
            return "failed"

        if not future.done():
            return "running"

        # Check if the future raised an exception
        exc = future.exception()
        if exc is not None:
            log.warning("sdk_worker_error", task_id=task_id, error=str(exc))
            return "failed"

        return "done"

    def reap(self, handle: WorkerHandle) -> WorkerResult:
        """Collect the result from a completed SDK agent.

        Prefers the review file written by the worker in the worktree.
        Falls back to the SDK future result if no review file is found.
        """
        task_id = handle.task_id
        worktree_path = self._worktrees.get(task_id)

        if worktree_path is None:
            worktree_path = os.path.join(self._worktree_base, task_id)

        # Try reading the worker-written review file first
        review_result = _read_review_from_worktree(worktree_path, task_id)
        if review_result is not None:
            result = review_result
        else:
            # Fall back to SDK future result
            future = self._futures.get(task_id)
            if future is not None and future.done() and future.exception() is None:
                result = future.result()
            else:
                result = WorkerResult(
                    verdict=Verdict.ERROR,
                    findings=0,
                    detail="Agent future missing or failed",
                )

        # Clean up
        self._futures.pop(task_id, None)
        self._worktrees.pop(task_id, None)
        cleanup_worktree(self._repo_path, worktree_path)

        return result

    def cancel(self, handle: WorkerHandle) -> None:
        """Cancel a running SDK agent and clean up."""
        task_id = handle.task_id
        future = self._futures.pop(task_id, None)
        if future is not None and not future.done():
            future.cancel()

        worktree_path = self._worktrees.pop(task_id, None)
        if worktree_path is None:
            worktree_path = os.path.join(self._worktree_base, task_id)

        branch = get_worktree_branch(worktree_path)
        cleanup_worktree(self._repo_path, worktree_path)
        delete_branch(self._repo_path, branch)

    def find_orphan(self, task_id: str, branch: str) -> WorkerHandle | None:
        """Check if a worktree exists for this task (crash recovery)."""
        import subprocess

        worktree_path = os.path.join(self._worktree_base, task_id)

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
            if result.stdout.strip() != branch:
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
        """Run a serial agent on trunk via the SDK. Blocks until complete."""
        log.info("sdk_serial_started", role=role)

        future = asyncio.run_coroutine_threadsafe(
            self._run_agent(prompt, self._repo_path), self._loop
        )

        try:
            future.result(timeout=600)
            log.info("sdk_serial_completed", role=role)
            return True
        except concurrent.futures.TimeoutError:
            log.warning("sdk_serial_timeout", role=role)
            future.cancel()
            return False
        except Exception:
            log.exception("sdk_serial_failed", role=role)
            return False

    # -- Private helpers -------------------------------------------------------

    async def _run_agent(self, prompt: str, cwd: str) -> WorkerResult:
        """Run a single agent query via the SDK. Returns a WorkerResult."""
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        # Clean GIT_* env vars so agents in worktrees don't inherit
        # stale GIT_DIR/GIT_INDEX_FILE from the orchestrator's context.
        cleaned_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

        options = ClaudeAgentOptions(
            cwd=cwd,
            permission_mode="bypassPermissions",
            model=self._model,
            env=cleaned_env,
        )

        result_text = ""
        is_error = False

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result_text = message.result or ""
                is_error = message.is_error

        if is_error:
            return WorkerResult(
                verdict=Verdict.ERROR,
                findings=0,
                detail=result_text or "Agent completed with error",
            )

        return WorkerResult(
            verdict=Verdict.PASS,
            findings=0,
            detail=result_text or "Agent completed",
        )


def _read_review_from_worktree(worktree_path: str, task_id: str) -> WorkerResult | None:
    """Read and parse a worker-written review file from a worktree.

    Globs for ``.hyperloop/state/reviews/{task_id}-round-*.md`` in the worktree,
    takes the last one (highest round), and parses YAML frontmatter for verdict,
    findings, and body detail.

    Returns None if no review file is found or if parsing fails.
    """
    pattern = os.path.join(worktree_path, ".hyperloop", "state", "reviews", f"{task_id}-round-*.md")
    matches = sorted(glob.glob(pattern))
    if not matches:
        return None

    review_path = matches[-1]
    try:
        with open(review_path) as f:
            content = f.read()

        match = re.match(r"^---\n(.*?\n)---\n(.*)", content, re.DOTALL)
        if match is None:
            return None

        fm_raw = yaml.safe_load(match.group(1))
        if not isinstance(fm_raw, dict):
            return None

        fm = cast("dict[str, object]", fm_raw)
        body = match.group(2)
        return WorkerResult(
            verdict=Verdict(str(fm["verdict"])),
            findings=int(str(fm["findings"])),
            detail=body.strip(),
        )
    except Exception:
        log.warning("review_parse_failed", worktree_path=worktree_path, task_id=task_id)
        return None
