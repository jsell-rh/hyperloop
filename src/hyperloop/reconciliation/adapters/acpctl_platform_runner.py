from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable

from hyperloop.reconciliation.models.executor_timeout_error import ExecutorTimeoutError
from hyperloop.reconciliation.models.platform_session import PlatformSession
from hyperloop.reconciliation.models.session_status import SessionStatus

EventCallback = Callable[[str, str, str], None]

_MAX_PREVIEW = 200
_TOOL_CALL_EVENTS = frozenset({"TOOL_CALL_START", "TOOL_CALL_ARGS"})


class AcpctlPlatformRunner:
    def __init__(
        self,
        *,
        acpctl_path: str = "acpctl",
        on_event: EventCallback | None = None,
    ) -> None:
        self._acpctl_path = acpctl_path
        self._on_event = on_event

    def create_session(
        self,
        *,
        name: str,
        prompt: str,
        repository_url: str,
        project: str,
        model: str | None,
        max_tokens: int | None = None,
    ) -> str:
        cmd = [
            self._acpctl_path,
            "create",
            "session",
            "--project-id",
            project,
            "--name",
            name,
            "--repo-url",
            repository_url,
            "--prompt",
            prompt,
            "-o",
            "json",
        ]
        if model is not None:
            cmd.extend(["--model", model])
        if max_tokens is not None:
            cmd.extend(["--max-tokens", str(max_tokens)])

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

    _SSE_BACKOFF = (2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0, 30.0)

    def wait_for_completion(
        self, session_id: str, *, timeout_seconds: int, branch: str = ""
    ) -> str:
        deadline = time.monotonic() + timeout_seconds
        last_message_text: str = ""

        for delay in self._SSE_BACKOFF:
            if time.monotonic() >= deadline:
                break

            finished, text = self._stream_events(session_id, branch, deadline)
            if text:
                last_message_text = text
            if finished:
                return last_message_text

            time.sleep(min(delay, max(0, deadline - time.monotonic())))

        raise ExecutorTimeoutError(
            f"Session {session_id} timed out after {timeout_seconds}s"
        )

    def _stream_events(
        self, session_id: str, branch: str, deadline: float
    ) -> tuple[bool, str]:
        proc = subprocess.Popen(
            [self._acpctl_path, "session", "events", session_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        last_message_text: str = ""
        current_message: list[str] = []
        finished = False
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type", "")
                self._dispatch_event(event_type, event, branch)

                if event_type == "TEXT_MESSAGE_START":
                    current_message = []
                elif event_type == "TEXT_MESSAGE_CONTENT":
                    current_message.append(event.get("delta", ""))
                elif event_type == "TEXT_MESSAGE_END":
                    last_message_text = "".join(current_message)
                    current_message = []
                elif event_type == "RUN_FINISHED":
                    finished = True

            remaining = max(0, deadline - time.monotonic())
            proc.wait(timeout=remaining or 1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return finished, last_message_text

    def _dispatch_event(
        self, event_type: str, event: dict[str, object], branch: str
    ) -> None:
        if self._on_event is None:
            return

        if event_type == "TEXT_MESSAGE_CONTENT":
            delta = str(event.get("delta", ""))
            if delta:
                self._on_event("text", branch, delta[:_MAX_PREVIEW])
        elif event_type in _TOOL_CALL_EVENTS:
            name = str(event.get("name", event.get("toolCallId", "")))
            args = str(event.get("args", ""))[:_MAX_PREVIEW]
            self._on_event("tool_use", branch, f"{name}: {args}")
        elif event_type == "RUN_STARTED":
            self._on_event("progress", branch, "Session started")
        elif event_type == "RUN_FINISHED":
            self._on_event("progress", branch, "Session completed")

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
        if data.get("completion_time"):
            return SessionStatus.STOPPED
        raw_phase = data.get("phase", "").lower()
        try:
            return SessionStatus(raw_phase)
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
