from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field

from hyperloop.reconciliation.models.event import Event, EventType, record_event


class TaskStatus(StrEnum):
    BACKLOG = "Backlog"
    IN_PROGRESS = "InProgress"
    COMPLETE = "Complete"
    FAILED = "Failed"


class Task(BaseModel):
    id: int
    depends_on: list[int] = []
    spec_path: str
    spec_blob_sha: str
    name: str
    description: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    retry_count: int = 0
    status: TaskStatus = TaskStatus.BACKLOG
    events: list[Event] = []

    def record_event(
        self,
        *,
        reason: str,
        message: str,
        event_type: EventType,
        timestamp: datetime,
    ) -> None:
        record_event(
            self.events,
            reason=reason,
            message=message,
            event_type=event_type,
            timestamp=timestamp,
        )
