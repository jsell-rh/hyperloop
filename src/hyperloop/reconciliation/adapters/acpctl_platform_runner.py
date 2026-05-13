from __future__ import annotations

import json
import subprocess
from hyperloop.reconciliation.models.executor_timeout_error import ExecutorTimeoutError
from hyperloop.reconciliation.models.platform_session import PlatformSession


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
        cmd = [
            self._acpctl_path,
            "create",
            "session",
            "--project-id",
            project,
            "--name",
            name,
            "--prompt",
            prompt,
            "--repo-url",
            repository_url,
            "-o",
            "json",
        ]
        if model is not None:
            cmd.extend(["--model", model])

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
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
