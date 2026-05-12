from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class EventType(StrEnum):
    NORMAL = "Normal"
    WARNING = "Warning"


class Event(BaseModel):
    type: EventType
    reason: str
    count: int = 1
    first_timestamp: datetime
    last_timestamp: datetime
    message: str


def record_event(
    events: list[Event],
    *,
    reason: str,
    message: str,
    event_type: EventType,
    timestamp: datetime,
) -> None:
    for event in events:
        if event.reason == reason:
            event.count += 1
            event.last_timestamp = timestamp
            event.message = message
            return
    events.append(
        Event(
            type=event_type,
            reason=reason,
            count=1,
            first_timestamp=timestamp,
            last_timestamp=timestamp,
            message=message,
        )
    )
