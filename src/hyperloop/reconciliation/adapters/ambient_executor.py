from __future__ import annotations

import atexit
import json
import re
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from hyperloop.reconciliation.adapters.platform_runner import PlatformRunner
from hyperloop.reconciliation.models.executor_timeout_error import ExecutorTimeoutError
from hyperloop.reconciliation.models.integration_summary import IntegrationSummary
from hyperloop.reconciliation.models.proposed_task import ProposedTask
from hyperloop.reconciliation.models.session_status import SessionStatus


_ENCODE_MAP: dict[str, str] = {
    "%": "%25",
    "/": "%2F",
}


def _encode_branch(branch: str) -> str:
    return "".join(_ENCODE_MAP.get(ch, ch) for ch in branch)


def _decode_branch(encoded: str) -> str:
    result: list[str] = []
    i = 0
    while i < len(encoded):
        if encoded[i] == "%" and i + 2 < len(encoded):
            hex_chars = encoded[i + 1 : i + 3]
            try:
                result.append(chr(int(hex_chars, 16)))
                i += 3
                continue
            except ValueError:
                pass
        result.append(encoded[i])
        i += 1
    return "".join(result)


_JSON_FENCE_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


def _extract_json(commit_message: str) -> str:
    match = _JSON_FENCE_RE.search(commit_message)
    if match:
        return match.group(1).strip()
    raise ValueError(f"No JSON block found in commit message: {commit_message[:200]}")


def _derive_session_prefix(branch_prefix: str) -> str:
    return _encode_branch(branch_prefix.rstrip("/")) + "-"


class AmbientExecutor:
    def __init__(
        self,
        repo_path: Path,
        *,
        platform_runner: PlatformRunner,
        repository_url: str,
        project_name: str,
        timeout_seconds: int = 300,
        max_retries: int = 3,
        max_tokens: int = 128000,
        branch_prefix: str = "hyperloop/",
    ) -> None:
        self._repo_path = repo_path
        self._platform_runner = platform_runner
        self._repository_url = repository_url
        self._project_name = project_name
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._max_tokens = max_tokens
        self._branch_prefix = branch_prefix
        self._session_prefix = _derive_session_prefix(branch_prefix)
        self._sessions: dict[str, str] = {}

        atexit.register(self._cleanup_all_sessions)

    def start_task_agent(
        self, *, branch: str, prompt: str, model: str | None = None
    ) -> None:
        self._start_async_agent(branch=branch, prompt=prompt, model=model)

    def start_verification_agent(
        self, *, branch: str, prompt: str, model: str | None = None
    ) -> None:
        self._start_async_agent(branch=branch, prompt=prompt, model=model)

    def run_decomposition(
        self, *, prompt: str, model: str | None = None
    ) -> list[ProposedTask]:
        commit_message = self._run_sync(prompt=prompt, model=model)
        raw = json.loads(_extract_json(commit_message))
        return [ProposedTask(**item) for item in raw]

    def resolve_merge(
        self,
        *,
        task_branch: str,
        delivery_branch: str,
        prompt: str,
        model: str | None = None,
    ) -> bool:
        commit_message = self._run_sync(prompt=prompt, model=model)
        raw = json.loads(_extract_json(commit_message))
        return bool(raw["resolved"])

    def compose_summary(
        self, *, prompt: str, model: str | None = None
    ) -> IntegrationSummary:
        commit_message = self._run_sync(prompt=prompt, model=model)
        raw = json.loads(_extract_json(commit_message))
        return IntegrationSummary(**raw)

    def check_health(self) -> list[str]:
        terminated: list[str] = []
        for branch, session_id in list(self._sessions.items()):
            status = self._platform_runner.get_session_status(session_id)
            if status in (SessionStatus.STOPPED, SessionStatus.FAILED):
                self._sessions.pop(branch, None)
                terminated.append(branch)
        return terminated

    def cancel(self, *, branch: str) -> None:
        session_id = self._sessions.pop(branch, None)
        if session_id is not None:
            self._platform_runner.stop_session(session_id)

    def detect_stale(self) -> list[str]:
        sessions = self._platform_runner.list_sessions(project=self._project_name)
        stale: list[str] = []
        for session in sessions:
            branch = self._branch_from_session_name(session.name)
            if branch is not None:
                stale.append(branch)
        return stale

    def _session_name(self, branch: str) -> str:
        return self._session_prefix + _encode_branch(branch)

    def _branch_from_session_name(self, name: str) -> str | None:
        if not name.startswith(self._session_prefix):
            return None
        encoded = name[len(self._session_prefix) :]
        return _decode_branch(encoded)

    def _start_async_agent(
        self, *, branch: str, prompt: str, model: str | None
    ) -> None:
        self._push_branch(branch)
        session_name = self._session_name(branch)

        def _create() -> str:
            return self._platform_runner.create_session(
                name=session_name,
                prompt=prompt,
                repository_url=self._repository_url,
                project=self._project_name,
                model=model,
                max_tokens=self._max_tokens,
            )

        session_id = self._retry(_create)
        self._sessions[branch] = session_id

    def _run_sync(self, *, prompt: str, model: str | None) -> str:
        tmp_suffix = uuid.uuid4().hex[:12]
        tmp_branch = f"{self._branch_prefix}tmp-{tmp_suffix}"
        self._git("branch", "--", tmp_branch, "HEAD")
        self._push_branch(tmp_branch)

        session_name = f"{self._session_prefix}sync-{tmp_suffix}"

        def _create() -> str:
            return self._platform_runner.create_session(
                name=session_name,
                prompt=prompt,
                repository_url=self._repository_url,
                project=self._project_name,
                model=model,
                max_tokens=self._max_tokens,
            )

        head_before = self._git("rev-parse", tmp_branch).stdout.strip()
        session_id = self._retry(_create)
        try:
            return self._await_result(session_id, tmp_branch, head_before)
        finally:
            self._platform_runner.stop_session(session_id)
            self._git("push", "origin", "--delete", tmp_branch, check=False)
            self._git("branch", "-D", "--", tmp_branch, check=False)

    def _await_result(self, session_id: str, branch: str, head_before: str) -> str:
        self._platform_runner.wait_for_completion(
            session_id, timeout_seconds=self._timeout_seconds
        )

        self._git("fetch", "origin", branch, check=False)
        head_after = self._git("rev-parse", f"origin/{branch}").stdout.strip()
        if head_after != head_before:
            result = self._git("log", "-1", "--format=%B", f"origin/{branch}")
            return result.stdout.strip()

        raise ValueError("Agent completed without creating a result commit")

    def _push_branch(self, branch: str) -> None:
        self._retry(lambda: self._git("push", "origin", branch))

    def _cleanup_all_sessions(self) -> None:
        for session_id in self._sessions.values():
            try:
                self._platform_runner.stop_session(session_id)
            except Exception:
                pass
        self._sessions.clear()

    def _retry[T](self, fn: Callable[[], T]) -> T:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return fn()
            except ExecutorTimeoutError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < self._max_retries:
                    time.sleep(0.01 * (2**attempt))
                    continue
                raise
        raise last_error  # type: ignore[misc]

    def _git(
        self,
        *args: str,
        check: bool = True,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self._repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=check,
        )
