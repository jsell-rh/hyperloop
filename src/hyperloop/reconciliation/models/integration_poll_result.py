from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class IntegrationPollStatus(StrEnum):
    PENDING = "Pending"
    MERGED = "Merged"
    CONFLICT = "Conflict"
    CLOSED = "Closed"
    FAILED = "Failed"


class IntegrationPollResult(BaseModel, frozen=True):
    status: IntegrationPollStatus
    conflict_details: str | None = None
