"""SpecSource port — interface for reading desired state (specs).

Implementations: GitSpecSource (git diff + git show).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SpecChange:
    """A spec file that changed since the last version."""

    path: str
    change_type: str  # "added", "modified", "deleted"


class SpecSource(Protocol):
    """Where to read desired state."""

    def detect_changes(self, since: str | None) -> list[SpecChange]:
        """Return spec files that changed since the given version marker.
        If since is None (first run), return all specs."""
        ...

    def read(self, spec_ref: str) -> str:
        """Read spec content at a pinned version (e.g. path@sha)."""
        ...

    def current_version(self) -> str:
        """Return the current version marker (for tracking last-processed)."""
        ...
