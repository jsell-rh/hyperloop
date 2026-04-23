"""FakeSpecSource -- in-memory SpecSource for testing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperloop.ports.spec_source import SpecChange


class FakeSpecSource:
    """In-memory SpecSource implementation.

    Seed specs via ``add_spec``, configure changes via ``set_changes``,
    and set the version marker via ``set_version``.
    """

    def __init__(self) -> None:
        self._specs: dict[str, str] = {}  # path -> content
        self._changes: list[SpecChange] = []
        self._version: str = "fake-v1"
        self._changed_since: set[str] = set()  # spec paths that have changed

    def add_spec(self, path: str, content: str) -> None:
        """Seed a spec file into the in-memory store."""
        self._specs[path] = content

    def set_changes(self, changes: list[SpecChange]) -> None:
        """Pre-configure the list of changes returned by detect_changes."""
        self._changes = changes

    def set_version(self, version: str) -> None:
        """Set the current version marker."""
        self._version = version

    def detect_changes(self, since: str | None) -> list[SpecChange]:
        """Return pre-configured changes."""
        return list(self._changes)

    def read(self, spec_ref: str) -> str:
        """Read a spec by path. Strips ``@version`` suffix if present."""
        path = spec_ref.split("@")[0] if "@" in spec_ref else spec_ref
        return self._specs.get(path, "")

    def mark_changed(self, spec_path: str) -> None:
        """Mark a spec as having changed since its pinned version."""
        self._changed_since.add(spec_path)

    def current_version(self) -> str:
        """Return the pre-configured version marker."""
        return self._version

    def has_changed(self, spec_path: str, since_version: str) -> bool:
        """Return whether the spec has been marked as changed."""
        return spec_path in self._changed_since
