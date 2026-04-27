"""SpecSource port — interface for reading desired state (specs).

Implementations: GitSpecSource (git diff + git show).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from hyperloop.domain.model import SpecChangeType


@dataclass(frozen=True)
class SpecChange:
    """A spec file that changed since the last version."""

    path: str
    change_type: SpecChangeType


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

    def file_version(self, spec_path: str) -> str:
        """Return the content-based version of a single spec file (e.g. blob SHA)."""
        ...

    def file_version_at(self, spec_path: str, ref: str) -> str:
        """Resolve a ref (commit or blob) to the blob SHA for a file at that ref."""
        ...

    def has_changed(self, spec_path: str, since_version: str) -> bool:
        """Return True if the spec file has changed since the given version."""
        ...

    def get_diff(self, spec_path: str, since_version: str) -> str:
        """Return the diff of a spec file since the given version.

        Returns empty string if no diff is available.
        """
        ...
