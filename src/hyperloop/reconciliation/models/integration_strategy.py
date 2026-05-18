from __future__ import annotations

from enum import StrEnum


class IntegrationStrategy(StrEnum):
    PR = "pr"
    PR_AUTOMERGE = "pr_automerge"
    DIRECT = "direct"
