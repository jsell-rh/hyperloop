"""Shared helpers for reading and parsing FileProbe JSONL events."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def find_events_path(repo_path: Path) -> Path | None:
    """Find the JSONL events file in the cache directory."""
    repo_hash = hashlib.md5(str(repo_path).encode()).hexdigest()[:8]
    events_path = Path.home() / ".cache" / "hyperloop" / repo_hash / "events.jsonl"
    if events_path.exists():
        return events_path

    # Legacy: check pointer file in repo (older versions wrote it there)
    pointer = repo_path / ".hyperloop" / ".dashboard-events-path"
    if pointer.exists():
        text = pointer.read_text().strip()
        if text:
            return Path(text)

    return None


def find_events_path_by_hash(repo_hash: str) -> Path | None:
    """Resolve events path directly from a repo hash."""
    events_path = Path.home() / ".cache" / "hyperloop" / repo_hash / "events.jsonl"
    if events_path.exists():
        return events_path
    return None


def parse_events(events_path: Path) -> list[dict[str, Any]]:
    """Read and parse JSONL events file, skipping malformed lines."""
    events: list[dict[str, Any]] = []
    try:
        text = events_path.read_text()
    except OSError:
        return events
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def discover_instances() -> list[tuple[str, Path, Path]]:
    """Return (repo_hash, repo_path, events_path) for all hyperloop instances.

    Scans ``~/.cache/hyperloop/*/`` directories.  Each valid instance must
    have both a ``repo-path`` file and an ``events.jsonl`` file.
    """
    cache_dir = Path.home() / ".cache" / "hyperloop"
    if not cache_dir.is_dir():
        return []

    instances: list[tuple[str, Path, Path]] = []
    for entry in sorted(cache_dir.iterdir()):
        if not entry.is_dir():
            continue
        repo_path_file = entry / "repo-path"
        events_file = entry / "events.jsonl"
        if not repo_path_file.exists():
            continue
        try:
            repo_path_str = repo_path_file.read_text().strip()
        except OSError:
            continue
        if not repo_path_str:
            continue
        instances.append((entry.name, Path(repo_path_str), events_file))

    return instances


def parse_events_tail(events_path: Path, max_lines: int = 500) -> list[dict[str, Any]]:
    """Parse only the last N lines of an events file for fleet summary.

    More efficient than reading the entire file for large event logs.
    """
    if not events_path.exists():
        return []
    try:
        text = events_path.read_text()
    except OSError:
        return []

    lines = text.strip().splitlines()
    tail = lines[-max_lines:] if len(lines) > max_lines else lines

    events: list[dict[str, Any]] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events
