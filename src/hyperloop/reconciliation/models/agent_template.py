from __future__ import annotations

from pydantic import BaseModel


class AgentTemplate(BaseModel, frozen=True):
    name: str
    prompt: str
    guidelines: list[str] = []
