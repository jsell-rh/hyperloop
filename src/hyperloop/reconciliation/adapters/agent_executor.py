from __future__ import annotations

from typing import Protocol

from hyperloop.reconciliation.models.event import Event
from hyperloop.reconciliation.models.integration_summary import IntegrationSummary
from hyperloop.reconciliation.models.proposed_task import ProposedTask
from hyperloop.reconciliation.models.spec_diff import SpecDiff
from hyperloop.reconciliation.models.task import Task
from hyperloop.reconciliation.models.task_briefing import TaskBriefing


class AgentExecutor(Protocol):
    def start_task_agent(self, *, branch: str, briefing: TaskBriefing) -> None: ...

    def start_verification_agent(
        self,
        *,
        branch: str,
        spec_content: str,
        spec_path: str,
        spec_blob_sha: str,
    ) -> None: ...

    def run_decomposition(
        self,
        *,
        spec_diffs: list[SpecDiff],
        existing_tasks: list[Task],
        events: list[Event],
    ) -> list[ProposedTask]: ...

    def resolve_merge(
        self,
        *,
        task_branch: str,
        delivery_branch: str,
        conflict_details: str,
    ) -> bool: ...

    def compose_summary(
        self,
        *,
        spec_content: str,
        task_summaries: list[tuple[str, str]],
        verification_rationale: str,
    ) -> IntegrationSummary: ...
