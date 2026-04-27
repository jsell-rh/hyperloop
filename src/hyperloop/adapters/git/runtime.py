"""AgentSdkRuntime — runs workers via the Claude Agent SDK.

Uses ``claude_agent_sdk.query()`` to run agents in-process.  Each parallel
worker gets its own worktree; serial agents run on trunk.  The SDK handles
tool execution, context management, and clean exit.

Verdict is read from ``.hyperloop/worker-result.yaml`` in the worktree
(runtime-agnostic file transport).  Falls back to the SDK's
``ResultMessage.is_error`` flag if no verdict file is found.
"""

from __future__ import annotations

import asyncio
import os
import threading
from typing import TYPE_CHECKING, cast

import structlog

from hyperloop.adapters.git._worktree import (
    clean_git_env,
    cleanup_worktree,
    create_worktree,
    delete_branch,
    ensure_worktrees_gitignored,
    get_worktree_branch,
)
from hyperloop.domain.model import Verdict, WorkerHandle, WorkerPollStatus, WorkerResult

if TYPE_CHECKING:
    import concurrent.futures

    from hyperloop.ports.probe import OrchestratorProbe

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
        probe: OrchestratorProbe | None = None,
        serial_timeout: float = 3600.0,
        base_branch: str = "main",
    ) -> None:
        self._repo_path = repo_path
        self._worktree_base = worktree_base or f"{repo_path}/worktrees/workers"
        self._model = model
        self._probe = probe
        self._serial_timeout = serial_timeout
        self._base_branch = base_branch
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
        """Create a worktree and start an SDK agent session.

        Retries up to 3 times on transient failures, cleaning up partial
        worktrees before each retry.
        """
        from hyperloop.adapters.retry import retry_with_backoff

        def _do_spawn() -> WorkerHandle:
            worktree_path = os.path.join(self._worktree_base, task_id)

            os.makedirs(self._worktree_base, exist_ok=True)
            ensure_worktrees_gitignored(self._repo_path)
            create_worktree(self._repo_path, worktree_path, branch)

            try:
                # Submit the agent to the background event loop
                future = asyncio.run_coroutine_threadsafe(
                    self._run_agent(prompt, worktree_path, task_id=task_id, role=role),
                    self._loop,
                )
                self._futures[task_id] = future
                self._worktrees[task_id] = worktree_path
            except Exception:
                # Clean up partial worktree before propagating
                cleanup_worktree(self._repo_path, worktree_path)
                raise

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

        return retry_with_backoff(
            _do_spawn,
            role=role,
            operation="spawn",
            probe=self._probe,
            max_attempts=3,
        )

    def poll(self, handle: WorkerHandle) -> WorkerPollStatus:
        """Check if the SDK agent has completed."""
        task_id = handle.task_id
        future = self._futures.get(task_id)

        if future is None:
            return WorkerPollStatus.FAILED

        if not future.done():
            return WorkerPollStatus.RUNNING

        # Check if the future raised an exception
        exc = future.exception()
        if exc is not None:
            log.warning("sdk_worker_error", task_id=task_id, error=str(exc))
            return WorkerPollStatus.FAILED

        return WorkerPollStatus.DONE

    def reap(self, handle: WorkerHandle) -> WorkerResult:
        """Collect the result from a completed SDK agent.

        Reads verdict from .hyperloop/worker-result.yaml in the worktree.
        Falls back to SDK ResultMessage if no verdict file exists.
        The verdict file is stripped from the branch later by rebase_branch.
        """
        from hyperloop.adapters.verdict import read_verdict_file

        task_id = handle.task_id
        worktree_path = self._worktrees.get(task_id)

        if worktree_path is None:
            worktree_path = os.path.join(self._worktree_base, task_id)

        result = read_verdict_file(worktree_path)

        if result is None:
            future = self._futures.get(task_id)
            if future is not None and future.done() and future.exception() is None:
                result = future.result()
            else:
                result = WorkerResult(
                    verdict=Verdict.FAIL,
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

    def run_auditor(self, spec_ref: str, prompt: str) -> WorkerResult:
        """Run an isolated read-only auditor in a detached worktree.

        Creates a detached worktree, runs the agent, reads the verdict from
        worker-result.yaml, cleans up, and returns the WorkerResult.
        Safe to call concurrently from multiple threads.
        """
        import uuid

        from hyperloop.adapters.retry import retry_with_backoff
        from hyperloop.adapters.verdict import read_verdict_file

        worktree_id = uuid.uuid4().hex[:8]
        worktree_path = os.path.join(self._worktree_base, f"audit-{worktree_id}")

        log.info("sdk_auditor_started", spec_ref=spec_ref, worktree=worktree_path)

        def _do_auditor() -> WorkerResult:
            os.makedirs(self._worktree_base, exist_ok=True)
            ensure_worktrees_gitignored(self._repo_path)
            create_worktree(self._repo_path, worktree_path, branch=None)

            try:
                loop = asyncio.new_event_loop()
                try:
                    agent_result = loop.run_until_complete(
                        asyncio.wait_for(
                            self._run_agent(
                                prompt,
                                worktree_path,
                                task_id=f"audit-{spec_ref}",
                                role="auditor",
                            ),
                            timeout=self._serial_timeout,
                        )
                    )
                except TimeoutError:
                    log.warning("sdk_auditor_timeout", spec_ref=spec_ref)
                    raise
                except Exception:
                    log.exception("sdk_auditor_failed", spec_ref=spec_ref)
                    raise
                finally:
                    loop.close()

                # Prefer verdict file over SDK result
                file_result = read_verdict_file(worktree_path)
                return file_result if file_result is not None else agent_result
            finally:
                cleanup_worktree(self._repo_path, worktree_path)

        try:
            return retry_with_backoff(
                _do_auditor,
                role="auditor",
                operation="run_auditor",
                probe=self._probe,
                max_attempts=3,
            )
        except TimeoutError:
            return WorkerResult(verdict=Verdict.FAIL, detail="Auditor timed out")
        except Exception:
            return WorkerResult(verdict=Verdict.FAIL, detail="Auditor failed")

    def run_trunk_agent(self, role: str, prompt: str) -> WorkerResult:
        """Run a mutating agent on trunk via the SDK. Blocks until complete.

        Returns WorkerResult with the agent's actual verdict.
        Pushes trunk after success. Must NOT be called concurrently.
        Retries up to 3 times on transient failures.
        """
        from hyperloop.adapters.retry import retry_with_backoff

        log.info("sdk_trunk_agent_started", role=role)

        def _do_trunk() -> WorkerResult:
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    asyncio.wait_for(
                        self._run_agent(
                            prompt,
                            self._repo_path,
                            task_id=f"serial-{role}",
                            role=role,
                        ),
                        timeout=self._serial_timeout,
                    )
                )
                log.info("sdk_trunk_agent_completed", role=role)
                self._push_trunk()
                return result
            except TimeoutError:
                log.warning("sdk_trunk_agent_timeout", role=role)
                raise
            except Exception:
                log.exception("sdk_trunk_agent_failed", role=role)
                raise
            finally:
                loop.close()

        try:
            return retry_with_backoff(
                _do_trunk,
                role=role,
                operation="run_trunk_agent",
                probe=self._probe,
                max_attempts=3,
            )
        except TimeoutError:
            return WorkerResult(verdict=Verdict.FAIL, detail="Trunk agent timed out")
        except Exception:
            return WorkerResult(verdict=Verdict.FAIL, detail="Trunk agent failed")

    def _push_trunk(self) -> None:
        """Push trunk (base branch) to origin after serial agent commits."""
        import subprocess

        try:
            subprocess.run(
                ["git", "-C", self._repo_path, "push", "origin", self._base_branch],
                check=True,
                capture_output=True,
                text=True,
                env=clean_git_env(),
                timeout=30,
            )
            log.info("sdk_trunk_pushed", branch=self._base_branch)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            log.warning("sdk_trunk_push_failed", branch=self._base_branch, error=str(exc))

    # -- Private helpers -------------------------------------------------------

    async def _run_agent(
        self, prompt: str, cwd: str, task_id: str = "", role: str = ""
    ) -> WorkerResult:
        """Run a single agent query via the SDK. Returns a WorkerResult."""
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            query,
        )

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
            if isinstance(message, AssistantMessage):
                self._emit_assistant_messages(message, task_id, role)
            elif isinstance(message, ResultMessage):
                result_text = message.result or ""
                is_error = message.is_error
                self._emit_probe(
                    task_id, role, "result", result_text[:200] if result_text else "done"
                )

        if is_error:
            return WorkerResult(
                verdict=Verdict.FAIL,
                detail=result_text or "Agent completed with error",
            )

        return WorkerResult(
            verdict=Verdict.PASS,
            detail=result_text or "Agent completed",
        )

    def _emit_assistant_messages(self, message: object, task_id: str, role: str) -> None:
        """Extract text and tool_use blocks from an AssistantMessage and emit probe events."""
        from claude_agent_sdk.types import TextBlock, ToolUseBlock

        content = getattr(message, "content", None)
        if not isinstance(content, list):
            return
        for block in cast("list[object]", content):
            if isinstance(block, TextBlock) and block.text:
                self._emit_probe(task_id, role, "text", block.text[:200])
            elif isinstance(block, ToolUseBlock):
                self._emit_probe(task_id, role, "tool_use", block.name)

    def _emit_probe(self, task_id: str, role: str, message_type: str, content: str) -> None:
        """Emit a worker_message probe event if a probe is configured."""
        if self._probe is None:
            return
        import contextlib

        with contextlib.suppress(Exception):
            self._probe.worker_message(
                task_id=task_id,
                role=role,
                message_type=message_type,
                content=content,
            )
