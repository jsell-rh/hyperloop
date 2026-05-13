from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SDKRunner(Protocol):
    def run_sync(
        self,
        *,
        prompt: str,
        cwd: Path,
        model: str | None,
        env: dict[str, str],
        timeout_seconds: int,
    ) -> str: ...

    def start_async(
        self,
        *,
        prompt: str,
        cwd: Path,
        model: str | None,
        env: dict[str, str],
    ) -> str: ...

    def stop(self, session_id: str) -> None: ...
