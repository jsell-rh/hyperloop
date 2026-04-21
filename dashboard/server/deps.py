"""Dependency injection for FastAPI — constructs read-only adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hyperloop.adapters.git.spec_source import GitSpecSource
from hyperloop.adapters.git.state import GitStateStore

if TYPE_CHECKING:
    from pathlib import Path

_state: GitStateStore | None = None
_spec_source: GitSpecSource | None = None
_repo_path: Path | None = None


def init(repo_path: Path) -> None:
    """Construct GitStateStore and GitSpecSource from a repo path."""
    global _state, _spec_source, _repo_path
    _repo_path = repo_path
    _state = GitStateStore(repo_path)
    _spec_source = GitSpecSource(repo_path)


def get_state() -> GitStateStore:
    """Return the configured StateStore instance."""
    assert _state is not None, "deps.init() must be called before get_state()"
    return _state


def get_spec_source() -> GitSpecSource:
    """Return the configured SpecSource instance."""
    assert _spec_source is not None, "deps.init() must be called before get_spec_source()"
    return _spec_source


def get_repo_path() -> Path:
    """Return the configured repo path."""
    assert _repo_path is not None, "deps.init() must be called before get_repo_path()"
    return _repo_path
