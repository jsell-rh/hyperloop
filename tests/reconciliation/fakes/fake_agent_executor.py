from __future__ import annotations

from hyperloop.reconciliation.models.integration_summary import IntegrationSummary
from hyperloop.reconciliation.models.proposed_task import ProposedTask


class FakeAgentExecutor:
    def __init__(self) -> None:
        self._decomposition_result: list[ProposedTask] = []
        self._decomposition_error: Exception | None = None
        self._start_task_error: Exception | None = None
        self._start_verification_error: Exception | None = None
        self._merge_result: bool = True
        self._integration_summary: IntegrationSummary = IntegrationSummary(
            title="Default title", body="Default body"
        )
        self._integration_summary_error: Exception | None = None
        self.started_tasks: list[tuple[str, str]] = []
        self.started_verifications: list[tuple[str, str]] = []
        self.decomposition_calls: list[str] = []
        self.merge_calls: list[tuple[str, str, str]] = []
        self.summary_calls: list[str] = []

    def set_decomposition_result(self, tasks: list[ProposedTask]) -> None:
        self._decomposition_result = tasks
        self._decomposition_error = None

    def set_decomposition_error(self, error: Exception) -> None:
        self._decomposition_error = error

    def set_merge_result(self, success: bool) -> None:
        self._merge_result = success

    def set_integration_summary(self, summary: IntegrationSummary) -> None:
        self._integration_summary = summary
        self._integration_summary_error = None

    def set_integration_summary_error(self, error: Exception) -> None:
        self._integration_summary_error = error

    def set_start_task_error(self, error: Exception) -> None:
        self._start_task_error = error

    def set_start_verification_error(self, error: Exception) -> None:
        self._start_verification_error = error

    def start_task_agent(self, *, branch: str, prompt: str) -> None:
        if self._start_task_error is not None:
            raise self._start_task_error
        self.started_tasks.append((branch, prompt))

    def start_verification_agent(self, *, branch: str, prompt: str) -> None:
        if self._start_verification_error is not None:
            raise self._start_verification_error
        self.started_verifications.append((branch, prompt))

    def run_decomposition(self, *, prompt: str) -> list[ProposedTask]:
        self.decomposition_calls.append(prompt)
        if self._decomposition_error is not None:
            raise self._decomposition_error
        return self._decomposition_result

    def resolve_merge(
        self,
        *,
        task_branch: str,
        delivery_branch: str,
        prompt: str,
    ) -> bool:
        self.merge_calls.append((task_branch, delivery_branch, prompt))
        return self._merge_result

    def compose_summary(self, *, prompt: str) -> IntegrationSummary:
        self.summary_calls.append(prompt)
        if self._integration_summary_error is not None:
            raise self._integration_summary_error
        return self._integration_summary
