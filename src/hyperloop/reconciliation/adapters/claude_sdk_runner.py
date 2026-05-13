from __future__ import annotations

import asyncio
import threading
import uuid
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage

from hyperloop.reconciliation.models.executor_timeout_error import ExecutorTimeoutError

_ALLOWED_TOOLS = [
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
    "Agent",
]


class _BackgroundSession:
    def __init__(
        self,
        client: ClaudeSDKClient,
        loop: asyncio.AbstractEventLoop,
        thread: threading.Thread,
    ) -> None:
        self.client = client
        self.loop = loop
        self.thread = thread


class ClaudeSDKRunner:
    def __init__(self) -> None:
        self._sessions: dict[str, _BackgroundSession] = {}

    def run_sync(
        self,
        *,
        prompt: str,
        cwd: Path,
        model: str | None,
        env: dict[str, str],
        timeout_seconds: int,
    ) -> str:
        async def _run() -> str:
            options = ClaudeAgentOptions(
                cwd=str(cwd),
                model=model,
                allowed_tools=_ALLOWED_TOOLS,
                permission_mode="bypass",
                env=env,
            )
            result_text = ""
            try:
                async with ClaudeSDKClient(options=options) as client:
                    await client.query(prompt)
                    async for message in client.receive_response():
                        if isinstance(message, ResultMessage):
                            result_text = message.result or ""
            except TimeoutError as exc:
                raise ExecutorTimeoutError(str(exc)) from exc
            return result_text

        try:
            return asyncio.run(asyncio.wait_for(_run(), timeout=timeout_seconds))
        except asyncio.TimeoutError as exc:
            raise ExecutorTimeoutError(
                f"Operation timed out after {timeout_seconds}s"
            ) from exc

    def start_async(
        self,
        *,
        prompt: str,
        cwd: Path,
        model: str | None,
        env: dict[str, str],
    ) -> str:
        session_id = str(uuid.uuid4())

        async def _run(client: ClaudeSDKClient) -> None:
            async with client:
                await client.query(prompt)
                async for _ in client.receive_response():
                    pass

        options = ClaudeAgentOptions(
            cwd=str(cwd),
            model=model,
            allowed_tools=_ALLOWED_TOOLS,
            permission_mode="bypass",
            env=env,
        )
        client = ClaudeSDKClient(options=options)
        loop = asyncio.new_event_loop()

        def _thread_target() -> None:
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_run(client))
            finally:
                loop.close()

        thread = threading.Thread(target=_thread_target, daemon=True)
        thread.start()
        self._sessions[session_id] = _BackgroundSession(
            client=client, loop=loop, thread=thread
        )
        return session_id

    def stop(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(
                session.client.interrupt(), session.loop
            )
            future.result(timeout=10)
        except Exception:
            pass
