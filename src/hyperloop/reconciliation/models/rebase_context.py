from __future__ import annotations

from pydantic import BaseModel


class RebaseContext(BaseModel, frozen=True):
    trunk_changes: str
