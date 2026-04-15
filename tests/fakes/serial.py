"""FakeSerialRunner — in-memory implementation of the SerialRunner port.

Records invocations for test assertions. Optionally runs a callback
to simulate side effects (e.g. creating task files in the state store).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class SerialRunRecord:
    """Record of a serial agent invocation."""

    role: str
    prompt: str


class FakeSerialRunner:
    """In-memory implementation of the SerialRunner port."""

    def __init__(self) -> None:
        self.runs: list[SerialRunRecord] = []
        self._callbacks: dict[str, Callable[[str], bool]] = {}
        self._default_success: bool = True

    def set_callback(self, role: str, callback: Callable[[str], bool]) -> None:
        """Register a callback for a role. Called with the prompt, returns success."""
        self._callbacks[role] = callback

    def set_default_success(self, success: bool) -> None:
        """Set the default return value when no callback is registered."""
        self._default_success = success

    # -- SerialRunner protocol -------------------------------------------------

    def run(self, role: str, prompt: str) -> bool:
        """Record the invocation and optionally execute a callback."""
        self.runs.append(SerialRunRecord(role=role, prompt=prompt))
        if role in self._callbacks:
            return self._callbacks[role](prompt)
        return self._default_success
