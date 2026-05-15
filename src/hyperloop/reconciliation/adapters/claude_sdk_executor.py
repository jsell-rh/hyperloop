from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from hyperloop.reconciliation.adapters.sdk_runner import SDKRunner
from hyperloop.reconciliation.models.executor_timeout_error import ExecutorTimeoutError
from hyperloop.reconciliation.models.integration_summary import IntegrationSummary
from hyperloop.reconciliation.models.proposed_task import ProposedTask

_GIT_ENV_VARS = frozenset(
    {
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_CEILING_DIRECTORIES",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_OBJECT_DIRECTORY",
        "GIT_NAMESPACE",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM",
    }
)

_DEFAULT_WORKTREE_DIR = ".hyperloop/worktrees"

_JSON_FENCE_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


def _sanitize_branch_for_path(branch: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", branch)


def _extract_json(commit_message: str) -> str:
    match = _JSON_FENCE_RE.search(commit_message)
    if match:
        return match.group(1).strip()
    raise ValueError(f"No JSON block found in commit message: {commit_message[:200]}")


class ClaudeSDKExecutor:
    def __init__(
        self,
        repo_path: Path,
        *,
        sdk_runner: SDKRunner,
        timeout_seconds: int = 300,
        max_retries: int = 3,
        branch_prefix: str = "hyperloop/",
        worktree_dir: str = _DEFAULT_WORKTREE_DIR,
    ) -> None:
        self._repo_path = repo_path
        self._sdk_runner = sdk_runner
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._branch_prefix = branch_prefix
        self._worktree_base = repo_path / worktree_dir
        self._sessions: dict[str, str] = {}
        self._worktrees: dict[str, Path] = {}

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

    def cancel(self, *, branch: str) -> None:
        session_id = self._sessions.pop(branch, None)
        if session_id is not None:
            self._sdk_runner.stop(session_id)

        worktree_path = self._worktrees.pop(branch, None)
        if worktree_path is None:
            candidate = self._worktree_base / _sanitize_branch_for_path(branch)
            if candidate.exists():
                worktree_path = candidate
        if worktree_path is not None:
            self._remove_worktree(worktree_path)

    def detect_stale(self) -> list[str]:
        if not self._worktree_base.exists():
            return []

        stale: list[str] = []
        for entry in self._worktree_base.iterdir():
            if not entry.is_dir():
                continue
            branch = self._worktree_branch(entry)
            if branch is not None:
                stale.append(branch)
        return stale

    def is_alive(self, *, branch: str) -> bool:
        session_id = self._sessions.get(branch)
        if session_id is None:
            return False
        return self._sdk_runner.is_session_alive(session_id)

    def _start_async_agent(
        self, *, branch: str, prompt: str, model: str | None
    ) -> None:
        worktree_path = self._create_worktree(branch)
        env = self._filtered_env()

        try:

            def _start() -> str:
                return self._sdk_runner.start_async(
                    prompt=prompt, cwd=worktree_path, model=model, env=env
                )

            session_id = self._retry(_start)
        except Exception:
            self._remove_worktree(worktree_path)
            raise

        self._sessions[branch] = session_id
        self._worktrees[branch] = worktree_path

    def _run_sync(self, *, prompt: str, model: str | None) -> str:
        tmp_prefix = self._branch_prefix.rstrip("/").replace("/", "-")
        tmp_branch = f"{tmp_prefix}-tmp-{uuid.uuid4().hex[:12]}"
        self._git("branch", "--", tmp_branch, "HEAD")
        worktree_path = self._create_worktree(tmp_branch)
        env = self._filtered_env()

        try:
            head_before = self._git(
                "rev-parse", "HEAD", cwd=worktree_path
            ).stdout.strip()

            def _run() -> str:
                return self._sdk_runner.run_sync(
                    prompt=prompt,
                    cwd=worktree_path,
                    model=model,
                    env=env,
                    timeout_seconds=self._timeout_seconds,
                )

            self._retry(_run)

            head_after = self._git(
                "rev-parse", "HEAD", cwd=worktree_path
            ).stdout.strip()
            if head_after == head_before:
                raise ValueError("Agent completed without creating a result commit")

            result = self._git("log", "-1", "--format=%B", cwd=worktree_path)
            return result.stdout.strip()
        finally:
            self._remove_worktree(worktree_path)
            self._git("branch", "-D", "--", tmp_branch, check=False)

    def _create_worktree(self, branch: str) -> Path:
        self._worktree_base.mkdir(parents=True, exist_ok=True)
        dirname = _sanitize_branch_for_path(branch)
        worktree_path = self._worktree_base / dirname
        if worktree_path.exists():
            self._remove_worktree(worktree_path)
            self._git("worktree", "prune", check=False)
        self._git("worktree", "add", str(worktree_path), "--", branch)
        return worktree_path

    def _remove_worktree(self, worktree_path: Path) -> None:
        self._git("worktree", "remove", "--force", str(worktree_path), check=False)

    def _worktree_branch(self, worktree_path: Path) -> str | None:
        head_file = worktree_path / ".git"
        if not head_file.exists():
            return None
        try:
            result = self._git("rev-parse", "--abbrev-ref", "HEAD", cwd=worktree_path)
            branch = result.stdout.strip()
            return branch if branch and branch != "HEAD" else None
        except subprocess.CalledProcessError:
            return None

    def _filtered_env(self) -> dict[str, str]:
        return {k: v for k, v in os.environ.items() if k not in _GIT_ENV_VARS}

    def _retry[T](self, fn: "Callable[[], T]") -> T:
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
            env=self._filtered_env(),
        )
