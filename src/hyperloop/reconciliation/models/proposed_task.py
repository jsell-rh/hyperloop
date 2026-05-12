from __future__ import annotations

from pydantic import BaseModel


class ProposedTask(BaseModel, frozen=True):
    name: str
    description: str
    spec_path: str
    spec_blob_sha: str
    depends_on: list[str] = []
