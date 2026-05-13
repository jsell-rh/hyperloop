from __future__ import annotations

from typing import Protocol

from hyperloop.reconciliation.models.platform_session import PlatformSession
from hyperloop.reconciliation.models.session_status import SessionStatus


class PlatformRunner(Protocol):
    def create_session(
        self,
        *,
        name: str,
        prompt: str,
        repository_url: str,
        project: str,
        model: str | None,
    ) -> str: ...

    def stop_session(self, session_id: str) -> None: ...

    def wait_for_completion(self, session_id: str, *, timeout_seconds: int) -> str: ...

    def list_sessions(self, *, project: str) -> list[PlatformSession]: ...

    def get_session_status(self, session_id: str) -> SessionStatus: ...
