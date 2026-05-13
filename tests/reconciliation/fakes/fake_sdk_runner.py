from __future__ import annotations

import subprocess
import uuid
from pathlib import Path


class FakeSDKRunner:
    def __init__(self) -> None:
        self._sync_commit_message: str = ""
        self._sync_error: Exception | None = None
        self._async_error: Exception | None = None
        self._transient_failures_remaining: int = 0
        self.sync_calls: list[dict[str, object]] = []
        self.async_calls: list[dict[str, object]] = []
        self.stopped_sessions: list[str] = []
        self._running_sessions: set[str] = set()

    def set_sync_result(self, result: str) -> None:
        self._sync_commit_message = f"Agent result\n\n```json\n{result}\n```"
        self._sync_error = None

    def set_sync_error(self, error: Exception) -> None:
        self._sync_error = error

    def set_async_error(self, error: Exception) -> None:
        self._async_error = error

    def set_transient_failures(self, count: int) -> None:
        self._transient_failures_remaining = count

    def run_sync(
        self,
        *,
        prompt: str,
        cwd: Path,
        model: str | None,
        env: dict[str, str],
        timeout_seconds: int,
    ) -> str:
        self.sync_calls.append(
            {
                "prompt": prompt,
                "cwd": cwd,
                "model": model,
                "env": dict(env),
                "timeout_seconds": timeout_seconds,
            }
        )
        if self._transient_failures_remaining > 0:
            self._transient_failures_remaining -= 1
            raise ConnectionError("transient failure")
        if self._sync_error is not None:
            raise self._sync_error
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", self._sync_commit_message],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        return ""

    def start_async(
        self,
        *,
        prompt: str,
        cwd: Path,
        model: str | None,
        env: dict[str, str],
    ) -> str:
        self.async_calls.append(
            {
                "prompt": prompt,
                "cwd": cwd,
                "model": model,
                "env": dict(env),
            }
        )
        if self._transient_failures_remaining > 0:
            self._transient_failures_remaining -= 1
            raise ConnectionError("transient failure")
        if self._async_error is not None:
            raise self._async_error
        session_id = str(uuid.uuid4())
        self._running_sessions.add(session_id)
        return session_id

    def stop(self, session_id: str) -> None:
        self.stopped_sessions.append(session_id)
        self._running_sessions.discard(session_id)
