from __future__ import annotations

from pydantic import BaseModel


class PromptSection(BaseModel, frozen=True):
    heading: str
    content: str
