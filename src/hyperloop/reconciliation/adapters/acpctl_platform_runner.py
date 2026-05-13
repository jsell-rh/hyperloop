from __future__ import annotations

import json
import os
import subprocess
import tempfile

from hyperloop.reconciliation.models.executor_timeout_error import ExecutorTimeoutError
from hyperloop.reconciliation.models.platform_session import PlatformSession
from hyperloop.reconciliation.models.session_status import SessionStatus


class AcpctlPlatformRunner:
    def __init__(self, *, acpctl_path: str = "acpctl") -> None:
        self._acpctl_path = acpctl_path

    def create_session(
        self,
        *,
        name: str,
        prompt: str,
        repository_url: str,
        project: str,
        model: str | None,
    ) -> str:
        fd, prompt_file = tempfile.mkstemp(suffix=".prompt", text=True)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(prompt)

            shell_cmd = (
                '"$0" create session'
                ' --project-id "$1" --name "$2" --repo-url "$3"'
                ' --prompt "$(cat "$4")" -o json'
            )
            args = [self._acpctl_path, project, name, repository_url, prompt_file]
            if model is not None:
                shell_cmd += ' --model "$5"'
                args.append(model)

            result = subprocess.run(
                ["sh", "-c", shell_cmd, *args],
                capture_output=True,
                text=True,
                check=True,
            )
        finally:
            os.unlink(prompt_file)

        data = json.loads(result.stdout)
        return data["id"]

    def stop_session(self, session_id: str) -> None:
        subprocess.run(
            [self._acpctl_path, "stop", session_id],
            capture_output=True,
            text=True,
            check=False,
        )

    def wait_for_completion(self, session_id: str, *, timeout_seconds: int) -> str:
        try:
            result = subprocess.run(
                [
                    self._acpctl_path,
                    "session",
                    "messages",
                    session_id,
                    "-f",
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ExecutorTimeoutError(
                f"Session {session_id} timed out after {timeout_seconds}s"
            ) from exc

        return _extract_result(result.stdout)

    def list_sessions(self, *, project: str) -> list[PlatformSession]:
        result = subprocess.run(
            [
                self._acpctl_path,
                "get",
                "sessions",
                "--project-id",
                project,
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        return [
            PlatformSession(session_id=item["id"], name=item.get("name", ""))
            for item in data.get("items", [])
        ]

    def get_session_status(self, session_id: str) -> SessionStatus:
        result = subprocess.run(
            [self._acpctl_path, "get", "session", session_id, "-o", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return SessionStatus.UNKNOWN
        data = json.loads(result.stdout)
        raw_status = data.get("status", "").lower()
        try:
            return SessionStatus(raw_status)
        except ValueError:
            return SessionStatus.UNKNOWN


def _extract_result(event_stream: str) -> str:
    last_message_text: str = ""
    current_message: list[str] = []
    for line in event_stream.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type", "")
        if event_type == "TEXT_MESSAGE_START":
            current_message = []
        elif event_type == "TEXT_MESSAGE_CONTENT":
            current_message.append(event.get("delta", ""))
        elif event_type == "TEXT_MESSAGE_END":
            last_message_text = "".join(current_message)
            current_message = []

    return last_message_text
