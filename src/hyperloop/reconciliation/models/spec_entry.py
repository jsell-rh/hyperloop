from __future__ import annotations

from pydantic import BaseModel


class SpecEntry(BaseModel, frozen=True):
    path: str
    blob_sha: str
