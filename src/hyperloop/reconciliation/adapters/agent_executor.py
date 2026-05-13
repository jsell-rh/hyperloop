from __future__ import annotations

from typing import Protocol

from hyperloop.reconciliation.models.integration_summary import IntegrationSummary
from hyperloop.reconciliation.models.proposed_task import ProposedTask


class AgentExecutor(Protocol):
    def start_task_agent(
        self, *, branch: str, prompt: str, model: str | None = None
    ) -> None: ...

    def start_verification_agent(
        self, *, branch: str, prompt: str, model: str | None = None
    ) -> None: ...

    def run_decomposition(
        self, *, prompt: str, model: str | None = None
    ) -> list[ProposedTask]: ...

    def resolve_merge(
        self,
        *,
        task_branch: str,
        delivery_branch: str,
        prompt: str,
        model: str | None = None,
    ) -> bool: ...

    def compose_summary(
        self, *, prompt: str, model: str | None = None
    ) -> IntegrationSummary: ...

    def cancel(self, *, branch: str) -> None: ...

    def detect_stale(self) -> list[str]: ...
