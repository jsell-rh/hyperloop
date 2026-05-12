from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field

from hyperloop.reconciliation.models.agent_handle import AgentHandle
from hyperloop.reconciliation.models.event import Event, EventType, record_event
from hyperloop.reconciliation.models.integration_summary import IntegrationSummary
from hyperloop.reconciliation.models.task import Task


class SpecPlanStatus(StrEnum):
    OUT_OF_SYNC = "OutOfSync"
    RECONCILING = "Reconciling"
    VERIFYING = "Verifying"
    SYNCED = "Synced"
    FAILED = "Failed"


class SpecPlan(BaseModel):
    path: str
    blob_sha: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: SpecPlanStatus = SpecPlanStatus.OUT_OF_SYNC
    superseded: bool = False
    reconciliation_attempts: int = 0
    integration_attempts: int = 0
    redecomposition_count: int = 0
    verification_handle: AgentHandle | None = None
    delivery_workspace_id: str | None = None
    integration_summary: IntegrationSummary | None = None
    tasks: list[Task] = []
    events: list[Event] = []

    def record_event(
        self,
        *,
        reason: str,
        message: str,
        event_type: EventType,
        timestamp: datetime,
    ) -> None:
        record_event(
            self.events,
            reason=reason,
            message=message,
            event_type=event_type,
            timestamp=timestamp,
        )
