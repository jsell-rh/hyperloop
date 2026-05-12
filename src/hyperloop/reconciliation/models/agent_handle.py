from __future__ import annotations

from pydantic import BaseModel


class AgentHandle(BaseModel, frozen=True):
    id: str
