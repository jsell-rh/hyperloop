from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class MergeOutcome(StrEnum):
    SUCCESS = "Success"
    CONFLICT = "Conflict"


class MergeResult(BaseModel, frozen=True):
    outcome: MergeOutcome
    conflict_details: str | None = None
