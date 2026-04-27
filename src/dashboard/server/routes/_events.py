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
