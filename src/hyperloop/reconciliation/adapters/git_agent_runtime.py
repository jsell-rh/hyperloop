from __future__ import annotations

import re
import subprocess
from pathlib import Path

from hyperloop.reconciliation.models.agent_handle import AgentHandle
from hyperloop.reconciliation.models.poll_result import (
    AgentStatus,
    AgentVerdict,
    PollResult,
)

_TASK_STATUS_RE = re.compile(r"^Task-Status:\s*(Complete|Failed)\s*$", re.MULTILINE)
_VERIFICATION_STATUS_RE = re.compile(
    r"^Verification-Status:\s*(Pass|Fail)\s*$", re.MULTILINE
)

_TASK_BRANCH_PATTERN = re.compile(r"^hyperloop/spec/[^/]+/task/\d+$")
_VERIFIER_BRANCH_PATTERN = re.compile(r"^hyperloop/spec/[^/]+/verifier$")


class GitAgentRuntime:
    def __init__(self, repo_path: Path, *, remote: str = "origin") -> None:
        self._repo_path = repo_path
        self._remote = remote

    def poll(self, handle: AgentHandle) -> PollResult:
        self._fetch_branch(handle.id)
        message = self._latest_commit_message(handle.id)
        is_empty = self._is_empty_commit(handle.id)

        if not is_empty:
            return PollResult(status=AgentStatus.RUNNING)

        return self._parse_signal(message)

    def detect_orphans(self) -> list[AgentHandle]:
        self._fetch_all_hyperloop_branches()
        branches = self._list_remote_hyperloop_branches()
        orphans: list[AgentHandle] = []

        for branch in branches:
            if not (
                _TASK_BRANCH_PATTERN.match(branch)
                or _VERIFIER_BRANCH_PATTERN.match(branch)
            ):
                continue

            message = self._latest_commit_message_remote(branch)
            is_empty = self._is_empty_commit_remote(branch)

            if not is_empty or not self._has_signal(message):
                orphans.append(AgentHandle(id=branch))

        return orphans

    def cancel(self, handle: AgentHandle) -> None:
        self._git(
            "branch",
            "-D",
            handle.id,
            check=False,
        )
        self._git(
            "push",
            self._remote,
            "--delete",
            handle.id,
            check=False,
        )

    def _fetch_branch(self, branch: str) -> None:
        self._git(
            "fetch",
            self._remote,
            f"+refs/heads/{branch}:refs/heads/{branch}",
            check=False,
        )

    def _fetch_all_hyperloop_branches(self) -> None:
        self._git(
            "fetch",
            self._remote,
            "+refs/heads/hyperloop/*:refs/heads/hyperloop/*",
            check=False,
        )

    def _latest_commit_message(self, branch: str) -> str:
        result = self._git("log", "-1", "--format=%B", branch)
        return result.stdout.strip()

    def _latest_commit_message_remote(self, branch: str) -> str:
        result = self._git("log", "-1", "--format=%B", f"{self._remote}/{branch}")
        return result.stdout.strip()

    def _is_empty_commit(self, branch: str) -> bool:
        result = self._git("diff-tree", "--no-commit-id", "--name-only", "-r", branch)
        return result.stdout.strip() == ""

    def _is_empty_commit_remote(self, branch: str) -> bool:
        result = self._git(
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            f"{self._remote}/{branch}",
        )
        return result.stdout.strip() == ""

    def _list_remote_hyperloop_branches(self) -> list[str]:
        result = self._git(
            "for-each-ref",
            "--format=%(refname:strip=3)",
            f"refs/remotes/{self._remote}/hyperloop/",
        )
        if not result.stdout.strip():
            return []
        return [line for line in result.stdout.strip().splitlines()]

    def _parse_signal(self, message: str) -> PollResult:
        task_match = _TASK_STATUS_RE.search(message)
        if task_match:
            status_value = task_match.group(1)
            rationale = message[: task_match.start()].strip()
            if status_value == "Complete":
                return PollResult(
                    status=AgentStatus.COMPLETE,
                    rationale=rationale or None,
                )
            return PollResult(
                status=AgentStatus.FAILED,
                rationale=rationale or None,
            )

        verification_match = _VERIFICATION_STATUS_RE.search(message)
        if verification_match:
            verdict_value = verification_match.group(1)
            rationale = message[: verification_match.start()].strip()
            verdict = (
                AgentVerdict.PASS if verdict_value == "Pass" else AgentVerdict.FAIL
            )
            return PollResult(
                status=AgentStatus.COMPLETE,
                rationale=rationale or None,
                verdict=verdict,
            )

        return PollResult(status=AgentStatus.RUNNING)

    def _has_signal(self, message: str) -> bool:
        return bool(
            _TASK_STATUS_RE.search(message) or _VERIFICATION_STATUS_RE.search(message)
        )

    def _git(
        self,
        *args: str,
        input: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self._repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            input=input,
            check=check,
        )
