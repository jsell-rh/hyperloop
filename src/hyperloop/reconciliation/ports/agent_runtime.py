from __future__ import annotations

from typing import Protocol

from hyperloop.reconciliation.models.agent_handle import AgentHandle
from hyperloop.reconciliation.models.event import Event
from hyperloop.reconciliation.models.integration_summary import IntegrationSummary
from hyperloop.reconciliation.models.poll_result import PollResult
from hyperloop.reconciliation.models.proposed_task import ProposedTask
from hyperloop.reconciliation.models.rebase_context import RebaseContext
from hyperloop.reconciliation.models.spec_diff import SpecDiff
from hyperloop.reconciliation.models.task import Task
from hyperloop.reconciliation.models.task_briefing import TaskBriefing


class AgentRuntime(Protocol):
    def launch_decomposition(
        self,
        spec_diffs: list[SpecDiff],
        existing_tasks: list[Task],
        events: list[Event],
    ) -> list[ProposedTask]: ...

    def launch_task(self, briefing: TaskBriefing) -> AgentHandle: ...

    def poll(self, handle: AgentHandle) -> PollResult: ...

    def launch_verification(
        self,
        spec_content: str,
        spec_path: str,
        spec_blob_sha: str,
        workspace_id: str,
        rebase_context: RebaseContext | None = None,
    ) -> AgentHandle: ...

    def launch_merge_resolution(
        self,
        task_workspace_id: str,
        delivery_workspace_id: str,
        conflict_details: str,
    ) -> bool: ...

    def compose_integration_summary(
        self,
        spec_content: str,
        task_summaries: list[tuple[str, str]],
        verification_rationale: str,
    ) -> IntegrationSummary: ...

    def cancel(self, handle: AgentHandle) -> None: ...

    def detect_stale(self) -> list[AgentHandle]: ...
