from __future__ import annotations

from pydantic import BaseModel


class IntegrationSummary(BaseModel):
    model_config = {"frozen": True}

    title: str
    body: str
