from __future__ import annotations

from hyperloop.reconciliation.ports.observer import ChangeType


class NullProbe:
    def reconciler_started(self, *, spec_count: int, cycle: int) -> None:
        pass

    def reconciler_halted(self, *, reason: str, total_cycles: int) -> None:
        pass

    def cycle_started(
        self, *, cycle: int, specs_out_of_sync: int, tasks_in_progress: int
    ) -> None:
        pass

    def cycle_completed(
        self,
        *,
        cycle: int,
        duration_s: float,
        specs_out_of_sync: int,
        tasks_dispatched: int,
        tasks_completed: int,
        tasks_failed: int,
    ) -> None:
        pass

    def spec_divergence_detected(
        self, *, spec_path: str, blob_sha: str, change_type: ChangeType
    ) -> None:
        pass

    def spec_superseded(self, *, spec_path: str, old_sha: str, new_sha: str) -> None:
        pass

    def decomposition_started(self, *, specs_count: int, cycle: int) -> None:
        pass

    def decomposition_completed(
        self, *, specs_count: int, tasks_created: int, cycle: int, duration_s: float
    ) -> None:
        pass

    def decomposition_failed(self, *, reason: str, cycle: int) -> None:
        pass

    def task_created(
        self,
        *,
        task_id: int,
        spec_path: str,
        spec_blob_sha: str,
        name: str,
        depends_on: list[int],
    ) -> None:
        pass

    def task_dispatched(
        self,
        *,
        task_id: int,
        spec_path: str,
        spec_blob_sha: str,
        retry_count: int,
        cycle: int,
    ) -> None:
        pass

    def task_completed(
        self, *, task_id: int, spec_path: str, spec_blob_sha: str, cycle: int
    ) -> None:
        pass

    def task_failed(
        self,
        *,
        task_id: int,
        spec_path: str,
        spec_blob_sha: str,
        reason: str,
        retry_count: int,
        cycle: int,
    ) -> None:
        pass

    def task_retried(
        self,
        *,
        task_id: int,
        spec_path: str,
        reason: str,
        retry_count: int,
        cycle: int,
    ) -> None:
        pass

    def dependency_invalidated(
        self, *, task_id: int, spec_path: str, dependency_task_id: int, reason: str
    ) -> None:
        pass

    def task_merge_completed(self, *, task_id: int, spec_blob_sha: str) -> None:
        pass

    def task_merge_conflict(self, *, task_id: int, spec_blob_sha: str) -> None:
        pass

    def merge_resolution_launched(self, *, task_id: int, spec_blob_sha: str) -> None:
        pass

    def merge_resolution_completed(
        self, *, task_id: int, spec_blob_sha: str, success: bool
    ) -> None:
        pass

    def trunk_integration_started(
        self, *, spec_path: str, spec_blob_sha: str, integration_id: str
    ) -> None:
        pass

    def trunk_integration_completed(
        self, *, spec_path: str, spec_blob_sha: str, integration_id: str
    ) -> None:
        pass

    def trunk_integration_failed(
        self, *, spec_path: str, spec_blob_sha: str, reason: str
    ) -> None:
        pass

    def integration_polled(
        self,
        *,
        spec_path: str,
        spec_blob_sha: str,
        integration_id: str,
        status: str,
    ) -> None:
        pass

    def delivery_rebase_started(self, *, spec_path: str, spec_blob_sha: str) -> None:
        pass

    def delivery_rebase_completed(self, *, spec_path: str, spec_blob_sha: str) -> None:
        pass

    def delivery_rebase_failed(
        self, *, spec_path: str, spec_blob_sha: str, reason: str
    ) -> None:
        pass

    def verification_launched(
        self, *, spec_path: str, spec_blob_sha: str, cycle: int
    ) -> None:
        pass

    def verification_launch_failed(
        self, *, spec_path: str, spec_blob_sha: str, reason: str, cycle: int
    ) -> None:
        pass

    def verification_passed(
        self, *, spec_path: str, spec_blob_sha: str, rationale: str, cycle: int
    ) -> None:
        pass

    def verification_failed(
        self, *, spec_path: str, spec_blob_sha: str, rationale: str, cycle: int
    ) -> None:
        pass

    def spec_synced(
        self, *, spec_path: str, spec_blob_sha: str, total_tasks: int, cycle: int
    ) -> None:
        pass

    def spec_failed(
        self, *, spec_path: str, spec_blob_sha: str, reason: str, cycle: int
    ) -> None:
        pass

    def redecomposition_triggered(
        self, *, spec_path: str, spec_blob_sha: str, failed_task_count: int, cycle: int
    ) -> None:
        pass

    def agent_cancelled(self, *, task_id: int, spec_path: str, reason: str) -> None:
        pass

    def stale_agent_detected(self, *, task_id: int, spec_path: str) -> None:
        pass

    def agent_launch_failed(
        self, *, task_id: int, role: str, reason: str, cycle: int
    ) -> None:
        pass

    def agent_tool_use(self, *, branch: str, tool: str, input_preview: str) -> None:
        pass

    def agent_text(self, *, branch: str, text_preview: str) -> None:
        pass

    def agent_progress(self, *, branch: str, description: str) -> None:
        pass

    def agent_error(self, *, branch: str, error: str) -> None:
        pass

    def crash_recovery_started(self, *, stale_agent_count: int) -> None:
        pass

    def composer_rebuilt(self, *, template_count: int) -> None:
        pass

    def composer_rebuild_failed(self, *, reason: str) -> None:
        pass

    def plan_synced(self, *, cycle: int) -> None:
        pass
