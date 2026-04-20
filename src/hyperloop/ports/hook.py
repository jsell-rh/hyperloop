"""CycleHook port — extension point for cross-cutting cycle concerns.

Implementations: ProcessImproverHook.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from hyperloop.domain.model import WorkerResult


class CycleHook(Protocol):
    """Extension point called after workers are reaped each cycle."""

    def after_reap(self, *, results: dict[str, WorkerResult], cycle: int) -> None:
        """Called after all workers are reaped, with all results."""
        ...
