from __future__ import annotations

from hyperloop.reconciliation.models.agent_handle import AgentHandle
from hyperloop.reconciliation.models.event import Event
from hyperloop.reconciliation.models.integration_summary import IntegrationSummary
from hyperloop.reconciliation.models.poll_result import AgentStatus, PollResult
from hyperloop.reconciliation.models.proposed_task import ProposedTask
from hyperloop.reconciliation.models.spec_diff import SpecDiff
from hyperloop.reconciliation.models.task import Task
from hyperloop.reconciliation.models.task_briefing import TaskBriefing


class FakeAgentRuntime:
    def __init__(self) -> None:
        self._decomposition_result: list[ProposedTask] = []
        self._decomposition_error: Exception | None = None
        self._launch_task_error: Exception | None = None
        self._poll_results: dict[str, PollResult] = {}
        self._cancelled: set[str] = set()
        self._stale: list[AgentHandle] = []
        self._merge_result: bool = True
        self._integration_summary: IntegrationSummary = IntegrationSummary(
            title="Default title", body="Default body"
        )
        self._integration_summary_error: Exception | None = None
        self._next_handle_id: int = 0
        self.launched_tasks: list[TaskBriefing] = []
        self.launched_verifications: list[tuple[str, str, str, str]] = []
        self.launched_merge_resolutions: list[tuple[str, str, str]] = []
        self.decomposition_calls: list[
            tuple[list[SpecDiff], list[Task], list[Event]]
        ] = []
        self.compose_summary_calls: list[tuple[str, list[tuple[str, str]], str]] = []

    def set_decomposition_result(self, tasks: list[ProposedTask]) -> None:
        self._decomposition_result = tasks
        self._decomposition_error = None

    def set_decomposition_error(self, error: Exception) -> None:
        self._decomposition_error = error

    def set_launch_task_error(self, error: Exception) -> None:
        self._launch_task_error = error

    def set_poll_result(self, handle: AgentHandle, result: PollResult) -> None:
        self._poll_results[handle.id] = result

    def set_merge_result(self, success: bool) -> None:
        self._merge_result = success

    def set_integration_summary(self, summary: IntegrationSummary) -> None:
        self._integration_summary = summary
        self._integration_summary_error = None

    def set_integration_summary_error(self, error: Exception) -> None:
        self._integration_summary_error = error

    def set_stale(self, stale: list[AgentHandle]) -> None:
        self._stale = stale

    def launch_decomposition(
        self,
        spec_diffs: list[SpecDiff],
        existing_tasks: list[Task],
        events: list[Event],
    ) -> list[ProposedTask]:
        self.decomposition_calls.append((spec_diffs, existing_tasks, events))
        if self._decomposition_error is not None:
            raise self._decomposition_error
        return self._decomposition_result

    def launch_task(self, briefing: TaskBriefing) -> AgentHandle:
        if self._launch_task_error is not None:
            raise self._launch_task_error
        handle = AgentHandle(id=f"agent-{self._next_handle_id}")
        self._next_handle_id += 1
        self._poll_results[handle.id] = PollResult(status=AgentStatus.RUNNING)
        self.launched_tasks.append(briefing)
        return handle

    def poll(self, handle: AgentHandle) -> PollResult:
        return self._poll_results[handle.id]

    def launch_verification(
        self,
        spec_content: str,
        spec_path: str,
        spec_blob_sha: str,
        workspace_id: str,
    ) -> AgentHandle:
        handle = AgentHandle(id=f"agent-{self._next_handle_id}")
        self._next_handle_id += 1
        self._poll_results[handle.id] = PollResult(status=AgentStatus.RUNNING)
        self.launched_verifications.append(
            (spec_content, spec_path, spec_blob_sha, workspace_id)
        )
        return handle

    def launch_merge_resolution(
        self,
        task_workspace_id: str,
        delivery_workspace_id: str,
        conflict_details: str,
    ) -> bool:
        self.launched_merge_resolutions.append(
            (task_workspace_id, delivery_workspace_id, conflict_details)
        )
        return self._merge_result

    def compose_integration_summary(
        self,
        spec_content: str,
        task_summaries: list[tuple[str, str]],
        verification_rationale: str,
    ) -> IntegrationSummary:
        self.compose_summary_calls.append(
            (spec_content, task_summaries, verification_rationale)
        )
        if self._integration_summary_error is not None:
            raise self._integration_summary_error
        return self._integration_summary

    def cancel(self, handle: AgentHandle) -> None:
        self._cancelled.add(handle.id)
        self._poll_results.pop(handle.id, None)

    def is_cancelled(self, handle: AgentHandle) -> bool:
        return handle.id in self._cancelled

    def detect_stale(self) -> list[AgentHandle]:
        return self._stale
