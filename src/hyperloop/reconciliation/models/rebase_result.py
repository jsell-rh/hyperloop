from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class RebaseOutcome(StrEnum):
    SUCCESS = "Success"
    CONFLICT = "Conflict"


class RebaseResult(BaseModel, frozen=True):
    outcome: RebaseOutcome
    conflict_details: str | None = None
