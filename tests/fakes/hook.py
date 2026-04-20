"""FakeHook -- in-memory CycleHook for testing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperloop.domain.model import WorkerResult


class FakeHook:
    """Records after_reap calls for test assertions."""

    def __init__(self) -> None:
        self.after_reap_calls: list[tuple[dict[str, WorkerResult], int]] = []

    def after_reap(self, *, results: dict[str, WorkerResult], cycle: int) -> None:
        """Record an after_reap invocation."""
        self.after_reap_calls.append((dict(results), cycle))
