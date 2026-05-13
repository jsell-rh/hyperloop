from __future__ import annotations

from typing import Protocol

from hyperloop.reconciliation.models.integration_summary import IntegrationSummary
from hyperloop.reconciliation.models.proposed_task import ProposedTask


class AgentExecutor(Protocol):
    def start_task_agent(self, *, branch: str, prompt: str) -> None: ...

    def start_verification_agent(self, *, branch: str, prompt: str) -> None: ...

    def run_decomposition(self, *, prompt: str) -> list[ProposedTask]: ...

    def resolve_merge(
        self,
        *,
        task_branch: str,
        delivery_branch: str,
        prompt: str,
    ) -> bool: ...

    def compose_summary(self, *, prompt: str) -> IntegrationSummary: ...
