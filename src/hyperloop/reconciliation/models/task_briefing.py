from __future__ import annotations

from pydantic import BaseModel

from hyperloop.reconciliation.models.event import Event


class TaskBriefing(BaseModel, frozen=True):
    spec_content: str
    spec_path: str
    spec_blob_sha: str
    task_description: str
    events: list[Event] = []
    workspace_id: str
