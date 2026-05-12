from __future__ import annotations

from enum import StrEnum


class WorkspaceType(StrEnum):
    TASK = "task"
    VERIFICATION = "verification"
    DELIVERY = "delivery"
