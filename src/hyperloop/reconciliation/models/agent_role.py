from __future__ import annotations

from enum import StrEnum


class AgentRole(StrEnum):
    IMPLEMENTER = "implementer"
    DECOMPOSER = "decomposer"
    VERIFIER = "verifier"
    MERGE_RESOLVER = "merge-resolver"
    INTEGRATION_SUMMARIZER = "integration-summarizer"
