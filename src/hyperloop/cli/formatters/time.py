from __future__ import annotations

from datetime import datetime, timezone


def format_relative_time(timestamp: datetime, *, now: datetime | None = None) -> str:
    if now is None:
        now = datetime.now(timezone.utc)
    delta = now - timestamp
    total_seconds = int(delta.total_seconds())

    if total_seconds < 60:
        return f"{total_seconds}s ago"

    total_minutes = total_seconds // 60
    if total_minutes < 60:
        return f"{total_minutes}m ago"

    total_hours = total_minutes // 60
    if total_hours < 24:
        return f"{total_hours}h ago"

    total_days = total_hours // 24
    return f"{total_days}d ago"
