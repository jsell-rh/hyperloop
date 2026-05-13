from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from hyperloop.reconciliation.models.platform_session import PlatformSession
from hyperloop.reconciliation.models.session_status import SessionStatus


class FakePlatformRunner:
    def __init__(self, *, remote_path: Path | None = None) -> None:
        self._remote_path = remote_path
        self._sync_commit_message: str = ""
        self._sync_error: Exception | None = None
        self._create_error: Exception | None = None
        self._transient_failures_remaining: int = 0
        self.create_calls: list[dict[str, object]] = []
        self.stop_calls: list[str] = []
        self.wait_calls: list[dict[str, object]] = []
        self.list_calls: list[str] = []
        self._running_sessions: dict[str, str] = {}

    def set_sync_result(self, result: str) -> None:
        self._sync_commit_message = f"Agent result\n\n```json\n{result}\n```"
        self._sync_error = None

    def set_sync_error(self, error: Exception) -> None:
        self._sync_error = error

    def set_create_error(self, error: Exception) -> None:
        self._create_error = error

    def set_transient_failures(self, count: int) -> None:
        self._transient_failures_remaining = count

    def create_session(
        self,
        *,
        name: str,
        prompt: str,
        repository_url: str,
        project: str,
        model: str | None,
    ) -> str:
        self.create_calls.append(
            {
                "name": name,
                "prompt": prompt,
                "repository_url": repository_url,
                "project": project,
                "model": model,
            }
        )
        if self._transient_failures_remaining > 0:
            self._transient_failures_remaining -= 1
            raise ConnectionError("transient failure")
        if self._create_error is not None:
            raise self._create_error
        session_id = str(uuid.uuid4())
        self._running_sessions[session_id] = name
        return session_id

    def stop_session(self, session_id: str) -> None:
        self.stop_calls.append(session_id)
        self._running_sessions.pop(session_id, None)

    def wait_for_completion(self, session_id: str, *, timeout_seconds: int) -> str:
        self.wait_calls.append(
            {"session_id": session_id, "timeout_seconds": timeout_seconds}
        )
        if self._sync_error is not None:
            raise self._sync_error
        if self._remote_path is not None and self._sync_commit_message:
            self._commit_to_remote(self._sync_commit_message)
        return ""

    def _commit_to_remote(self, message: str) -> None:
        assert self._remote_path is not None
        result = subprocess.run(
            ["git", "branch", "--list"],
            cwd=self._remote_path,
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.splitlines():
            branch = line.strip().lstrip("* ")
            if "tmp-" not in branch:
                continue
            tree = subprocess.run(
                ["git", "rev-parse", f"{branch}^{{tree}}"],
                cwd=self._remote_path,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            parent = subprocess.run(
                ["git", "rev-parse", branch],
                cwd=self._remote_path,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            new_commit = subprocess.run(
                [
                    "git",
                    "commit-tree",
                    tree,
                    "-p",
                    parent,
                    "-m",
                    message,
                ],
                cwd=self._remote_path,
                capture_output=True,
                text=True,
                check=True,
                env={
                    "GIT_AUTHOR_NAME": "Fake",
                    "GIT_AUTHOR_EMAIL": "f@e.com",
                    "GIT_COMMITTER_NAME": "Fake",
                    "GIT_COMMITTER_EMAIL": "f@e.com",
                },
            ).stdout.strip()
            subprocess.run(
                ["git", "update-ref", f"refs/heads/{branch}", new_commit],
                cwd=self._remote_path,
                capture_output=True,
                text=True,
                check=True,
            )
            break

    def list_sessions(self, *, project: str) -> list[PlatformSession]:
        self.list_calls.append(project)
        return [
            PlatformSession(session_id=sid, name=name)
            for sid, name in self._running_sessions.items()
        ]

    def get_session_status(self, session_id: str) -> SessionStatus:
        if session_id in self._running_sessions:
            return SessionStatus.RUNNING
        return SessionStatus.STOPPED
