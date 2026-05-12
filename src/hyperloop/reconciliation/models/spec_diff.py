from __future__ import annotations

from pydantic import BaseModel


class SpecDiff(BaseModel, frozen=True):
    spec_path: str
    blob_sha: str
    diff_text: str
