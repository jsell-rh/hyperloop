from __future__ import annotations

from pydantic import BaseModel


class PlatformSession(BaseModel, frozen=True):
    session_id: str
    name: str
