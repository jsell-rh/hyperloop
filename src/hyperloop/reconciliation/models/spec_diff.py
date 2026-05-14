from __future__ import annotations

from pydantic import BaseModel


class SpecDiff(BaseModel, frozen=True):
    spec_path: str
    blob_sha: str
    old_blob_sha: str | None
    content: str
    diff_text: str
