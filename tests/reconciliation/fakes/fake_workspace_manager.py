from __future__ import annotations

from hyperloop.reconciliation.models.integration_poll_result import (
    IntegrationPollResult,
    IntegrationPollStatus,
)
from hyperloop.reconciliation.models.merge_result import (
    MergeOutcome,
    MergeResult,
)
from hyperloop.reconciliation.models.rebase_result import RebaseOutcome, RebaseResult


class FakeWorkspaceManager:
    def __init__(self) -> None:
        self._delivery_workspaces: set[str] = set()
        self._task_workspaces: dict[tuple[str, int], str] = {}
        self._task_briefings: dict[tuple[str, int], str] = {}
        self._verification_workspaces: set[str] = set()
        self._merge_results: dict[tuple[str, int], MergeResult] = {}
        self._integration_ids: dict[str, str] = {}
        self._poll_results: dict[str, IntegrationPollResult] = {}
        self._rebase_results: dict[str, RebaseResult] = {}
        self.integrations: list[tuple[str, str, str, str]] = []
        self.verification_cleanup_count: int = 0

    def set_merge_result(
        self, blob_sha: str, task_id: int, result: MergeResult
    ) -> None:
        self._merge_results[(blob_sha, task_id)] = result

    def set_integration_id(self, blob_sha: str, integration_id: str) -> None:
        self._integration_ids[blob_sha] = integration_id

    def set_poll_integration_result(
        self, integration_id: str, result: IntegrationPollResult
    ) -> None:
        self._poll_results[integration_id] = result

    def set_rebase_result(self, blob_sha: str, result: RebaseResult) -> None:
        self._rebase_results[blob_sha] = result

    def create_delivery_workspace(self, blob_sha: str) -> str:
        self._delivery_workspaces.add(blob_sha)
        return f"delivery/{blob_sha}"

    def create_task_workspace(self, blob_sha: str, task_id: int, briefing: str) -> str:
        if blob_sha not in self._delivery_workspaces:
            raise ValueError(f"No delivery workspace for blob_sha={blob_sha}")
        workspace_id = f"task/{blob_sha}/{task_id}"
        self._task_workspaces[(blob_sha, task_id)] = workspace_id
        self._task_briefings[(blob_sha, task_id)] = briefing
        return workspace_id

    def create_verification_workspace(self, blob_sha: str) -> str:
        if blob_sha not in self._delivery_workspaces:
            raise ValueError(f"No delivery workspace for blob_sha={blob_sha}")
        self._verification_workspaces.add(blob_sha)
        return f"verification/{blob_sha}"

    def merge_task(self, blob_sha: str, task_id: int) -> MergeResult:
        if blob_sha not in self._delivery_workspaces:
            raise ValueError(f"No delivery workspace for blob_sha={blob_sha}")
        if (blob_sha, task_id) not in self._task_workspaces:
            raise ValueError(
                f"No task workspace for blob_sha={blob_sha}, task_id={task_id}"
            )
        result = self._merge_results.get(
            (blob_sha, task_id),
            MergeResult(outcome=MergeOutcome.SUCCESS),
        )
        if result.outcome == MergeOutcome.SUCCESS:
            del self._task_workspaces[(blob_sha, task_id)]
            self._task_briefings.pop((blob_sha, task_id), None)
        return result

    def integrate(self, blob_sha: str, spec_path: str, title: str, body: str) -> str:
        if blob_sha not in self._delivery_workspaces:
            raise ValueError(f"No delivery workspace for blob_sha={blob_sha}")
        self.integrations.append((blob_sha, spec_path, title, body))
        return self._integration_ids.get(
            blob_sha, f"https://github.com/example/repo/pull/fake-{blob_sha}"
        )

    def poll_integration(self, integration_id: str) -> IntegrationPollResult:
        return self._poll_results.get(
            integration_id,
            IntegrationPollResult(status=IntegrationPollStatus.PENDING),
        )

    def rebase_delivery(self, blob_sha: str) -> RebaseResult:
        return self._rebase_results.get(
            blob_sha,
            RebaseResult(outcome=RebaseOutcome.SUCCESS),
        )

    def cleanup(self, blob_sha: str) -> None:
        self._delivery_workspaces.discard(blob_sha)
        self._verification_workspaces.discard(blob_sha)
        self._integration_ids.pop(blob_sha, None)
        keys_to_remove = [key for key in self._task_workspaces if key[0] == blob_sha]
        for key in keys_to_remove:
            del self._task_workspaces[key]
            self._task_briefings.pop(key, None)
            self._merge_results.pop(key, None)

    def cleanup_verification(self, blob_sha: str) -> None:
        self._verification_workspaces.discard(blob_sha)
        self.verification_cleanup_count += 1

    def has_delivery_workspace(self, blob_sha: str) -> bool:
        return blob_sha in self._delivery_workspaces

    def has_task_workspace(self, blob_sha: str, task_id: int) -> bool:
        return (blob_sha, task_id) in self._task_workspaces

    def has_verification_workspace(self, blob_sha: str) -> bool:
        return blob_sha in self._verification_workspaces

    def get_task_briefing(self, blob_sha: str, task_id: int) -> str:
        return self._task_briefings[(blob_sha, task_id)]
