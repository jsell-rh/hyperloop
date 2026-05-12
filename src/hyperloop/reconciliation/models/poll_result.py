from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class AgentStatus(StrEnum):
    RUNNING = "Running"
    COMPLETE = "Complete"
    FAILED = "Failed"


class AgentVerdict(StrEnum):
    PASS = "Pass"
    FAIL = "Fail"


class PollResult(BaseModel, frozen=True):
    status: AgentStatus
    rationale: str | None = None
    verdict: AgentVerdict | None = None
