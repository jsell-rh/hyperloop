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
        self._stale_branches: list[str] = []
        self._alive_branches: set[str] = set()
        self.started_tasks: list[tuple[str, str, str | None]] = []
        self.started_verifications: list[tuple[str, str, str | None]] = []
        self.decomposition_calls: list[tuple[str, str | None]] = []
        self.merge_calls: list[tuple[str, str, str, str | None]] = []
        self.summary_calls: list[tuple[str, str | None]] = []
        self.cancelled_branches: list[str] = []

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

    def set_stale_branches(self, branches: list[str]) -> None:
        self._stale_branches = list(branches)

    def set_alive(self, branch: str) -> None:
        self._alive_branches.add(branch)

    def set_not_alive(self, branch: str) -> None:
        self._alive_branches.discard(branch)

    def set_start_task_error(self, error: Exception) -> None:
        self._start_task_error = error

    def set_start_verification_error(self, error: Exception) -> None:
        self._start_verification_error = error

    def start_task_agent(
        self, *, branch: str, prompt: str, model: str | None = None
    ) -> None:
        if self._start_task_error is not None:
            raise self._start_task_error
        self.started_tasks.append((branch, prompt, model))
        self._alive_branches.add(branch)

    def start_verification_agent(
        self, *, branch: str, prompt: str, model: str | None = None
    ) -> None:
        if self._start_verification_error is not None:
            raise self._start_verification_error
        self.started_verifications.append((branch, prompt, model))
        self._alive_branches.add(branch)

    def run_decomposition(
        self, *, prompt: str, model: str | None = None
    ) -> list[ProposedTask]:
        self.decomposition_calls.append((prompt, model))
        if self._decomposition_error is not None:
            raise self._decomposition_error
        return self._decomposition_result

    def resolve_merge(
        self,
        *,
        task_branch: str,
        delivery_branch: str,
        prompt: str,
        model: str | None = None,
    ) -> bool:
        self.merge_calls.append((task_branch, delivery_branch, prompt, model))
        return self._merge_result

    def compose_summary(
        self, *, prompt: str, model: str | None = None
    ) -> IntegrationSummary:
        self.summary_calls.append((prompt, model))
        if self._integration_summary_error is not None:
            raise self._integration_summary_error
        return self._integration_summary

    def cancel(self, *, branch: str) -> None:
        self.cancelled_branches.append(branch)
        self._alive_branches.discard(branch)

    def detect_stale(self) -> list[str]:
        return list(self._stale_branches)

    def is_alive(self, *, branch: str) -> bool:
        return branch in self._alive_branches
