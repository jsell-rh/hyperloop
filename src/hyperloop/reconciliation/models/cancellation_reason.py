from __future__ import annotations

from enum import StrEnum


class CancellationReason(StrEnum):
    SUPERSEDED = "superseded"
    DEPENDENCY_INVALIDATED = "dependency_invalidated"
    ORPHANED = "orphaned"
