from __future__ import annotations

from hyperloop.reconciliation.ports.observer import ChangeType, Observer


class CompositeObserver:
    def __init__(self, adapters: list[Observer]) -> None:
        self._adapters = adapters

    def _fan_out(self, method_name: str, **kwargs: object) -> None:
        for adapter in self._adapters:
            try:
                getattr(adapter, method_name)(**kwargs)
            except Exception:
                pass

    def reconciler_started(self, *, spec_count: int, cycle: int) -> None:
        self._fan_out("reconciler_started", spec_count=spec_count, cycle=cycle)

    def reconciler_halted(self, *, reason: str, total_cycles: int) -> None:
        self._fan_out("reconciler_halted", reason=reason, total_cycles=total_cycles)

    def cycle_started(
        self, *, cycle: int, specs_out_of_sync: int, tasks_in_progress: int
    ) -> None:
        self._fan_out(
            "cycle_started",
            cycle=cycle,
            specs_out_of_sync=specs_out_of_sync,
            tasks_in_progress=tasks_in_progress,
        )

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
        self._fan_out(
            "cycle_completed",
            cycle=cycle,
            duration_s=duration_s,
            specs_out_of_sync=specs_out_of_sync,
            tasks_dispatched=tasks_dispatched,
            tasks_completed=tasks_completed,
            tasks_failed=tasks_failed,
        )

    def spec_divergence_detected(
        self, *, spec_path: str, blob_sha: str, change_type: ChangeType
    ) -> None:
        self._fan_out(
            "spec_divergence_detected",
            spec_path=spec_path,
            blob_sha=blob_sha,
            change_type=change_type,
        )

    def spec_superseded(self, *, spec_path: str, old_sha: str, new_sha: str) -> None:
        self._fan_out(
            "spec_superseded", spec_path=spec_path, old_sha=old_sha, new_sha=new_sha
        )

    def decomposition_started(self, *, specs_count: int, cycle: int) -> None:
        self._fan_out("decomposition_started", specs_count=specs_count, cycle=cycle)

    def decomposition_completed(
        self, *, specs_count: int, tasks_created: int, cycle: int, duration_s: float
    ) -> None:
        self._fan_out(
            "decomposition_completed",
            specs_count=specs_count,
            tasks_created=tasks_created,
            cycle=cycle,
            duration_s=duration_s,
        )

    def decomposition_failed(self, *, reason: str, cycle: int) -> None:
        self._fan_out("decomposition_failed", reason=reason, cycle=cycle)

    def task_created(
        self,
        *,
        task_id: int,
        spec_path: str,
        spec_blob_sha: str,
        name: str,
        depends_on: list[int],
    ) -> None:
        self._fan_out(
            "task_created",
            task_id=task_id,
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            name=name,
            depends_on=depends_on,
        )

    def task_dispatched(
        self,
        *,
        task_id: int,
        spec_path: str,
        spec_blob_sha: str,
        retry_count: int,
        cycle: int,
    ) -> None:
        self._fan_out(
            "task_dispatched",
            task_id=task_id,
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            retry_count=retry_count,
            cycle=cycle,
        )

    def task_completed(
        self, *, task_id: int, spec_path: str, spec_blob_sha: str, cycle: int
    ) -> None:
        self._fan_out(
            "task_completed",
            task_id=task_id,
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            cycle=cycle,
        )

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
        self._fan_out(
            "task_failed",
            task_id=task_id,
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            reason=reason,
            retry_count=retry_count,
            cycle=cycle,
        )

    def task_retried(
        self,
        *,
        task_id: int,
        spec_path: str,
        reason: str,
        retry_count: int,
        cycle: int,
    ) -> None:
        self._fan_out(
            "task_retried",
            task_id=task_id,
            spec_path=spec_path,
            reason=reason,
            retry_count=retry_count,
            cycle=cycle,
        )

    def dependency_invalidated(
        self, *, task_id: int, spec_path: str, dependency_task_id: int, reason: str
    ) -> None:
        self._fan_out(
            "dependency_invalidated",
            task_id=task_id,
            spec_path=spec_path,
            dependency_task_id=dependency_task_id,
            reason=reason,
        )

    def task_merge_completed(self, *, task_id: int, spec_blob_sha: str) -> None:
        self._fan_out(
            "task_merge_completed", task_id=task_id, spec_blob_sha=spec_blob_sha
        )

    def task_merge_conflict(self, *, task_id: int, spec_blob_sha: str) -> None:
        self._fan_out(
            "task_merge_conflict", task_id=task_id, spec_blob_sha=spec_blob_sha
        )

    def merge_resolution_launched(self, *, task_id: int, spec_blob_sha: str) -> None:
        self._fan_out(
            "merge_resolution_launched", task_id=task_id, spec_blob_sha=spec_blob_sha
        )

    def merge_resolution_completed(
        self, *, task_id: int, spec_blob_sha: str, success: bool
    ) -> None:
        self._fan_out(
            "merge_resolution_completed",
            task_id=task_id,
            spec_blob_sha=spec_blob_sha,
            success=success,
        )

    def trunk_integration_started(
        self, *, spec_path: str, spec_blob_sha: str, integration_id: str
    ) -> None:
        self._fan_out(
            "trunk_integration_started",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            integration_id=integration_id,
        )

    def trunk_integration_completed(
        self, *, spec_path: str, spec_blob_sha: str, integration_id: str
    ) -> None:
        self._fan_out(
            "trunk_integration_completed",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            integration_id=integration_id,
        )

    def trunk_integration_failed(
        self, *, spec_path: str, spec_blob_sha: str, reason: str
    ) -> None:
        self._fan_out(
            "trunk_integration_failed",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            reason=reason,
        )

    def integration_polled(
        self,
        *,
        spec_path: str,
        spec_blob_sha: str,
        integration_id: str,
        status: str,
    ) -> None:
        self._fan_out(
            "integration_polled",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            integration_id=integration_id,
            status=status,
        )

    def delivery_rebase_started(self, *, spec_path: str, spec_blob_sha: str) -> None:
        self._fan_out(
            "delivery_rebase_started",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
        )

    def delivery_rebase_completed(self, *, spec_path: str, spec_blob_sha: str) -> None:
        self._fan_out(
            "delivery_rebase_completed",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
        )

    def delivery_rebase_failed(
        self, *, spec_path: str, spec_blob_sha: str, reason: str
    ) -> None:
        self._fan_out(
            "delivery_rebase_failed",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            reason=reason,
        )

    def verification_launched(
        self, *, spec_path: str, spec_blob_sha: str, cycle: int
    ) -> None:
        self._fan_out(
            "verification_launched",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            cycle=cycle,
        )

    def verification_launch_failed(
        self, *, spec_path: str, spec_blob_sha: str, reason: str, cycle: int
    ) -> None:
        self._fan_out(
            "verification_launch_failed",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            reason=reason,
            cycle=cycle,
        )

    def verification_passed(
        self, *, spec_path: str, spec_blob_sha: str, rationale: str, cycle: int
    ) -> None:
        self._fan_out(
            "verification_passed",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            rationale=rationale,
            cycle=cycle,
        )

    def verification_failed(
        self, *, spec_path: str, spec_blob_sha: str, rationale: str, cycle: int
    ) -> None:
        self._fan_out(
            "verification_failed",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            rationale=rationale,
            cycle=cycle,
        )

    def spec_synced(
        self, *, spec_path: str, spec_blob_sha: str, total_tasks: int, cycle: int
    ) -> None:
        self._fan_out(
            "spec_synced",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            total_tasks=total_tasks,
            cycle=cycle,
        )

    def spec_failed(
        self, *, spec_path: str, spec_blob_sha: str, reason: str, cycle: int
    ) -> None:
        self._fan_out(
            "spec_failed",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            reason=reason,
            cycle=cycle,
        )

    def redecomposition_triggered(
        self, *, spec_path: str, spec_blob_sha: str, failed_task_count: int, cycle: int
    ) -> None:
        self._fan_out(
            "redecomposition_triggered",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            failed_task_count=failed_task_count,
            cycle=cycle,
        )

    def agent_cancelled(self, *, task_id: int, spec_path: str, reason: str) -> None:
        self._fan_out(
            "agent_cancelled", task_id=task_id, spec_path=spec_path, reason=reason
        )

    def stale_agent_detected(self, *, task_id: int, spec_path: str) -> None:
        self._fan_out("stale_agent_detected", task_id=task_id, spec_path=spec_path)

    def agent_launch_failed(
        self, *, task_id: int, role: str, reason: str, cycle: int
    ) -> None:
        self._fan_out(
            "agent_launch_failed",
            task_id=task_id,
            role=role,
            reason=reason,
            cycle=cycle,
        )

    def agent_tool_use(self, *, branch: str, tool: str, input_preview: str) -> None:
        self._fan_out(
            "agent_tool_use", branch=branch, tool=tool, input_preview=input_preview
        )

    def agent_text(self, *, branch: str, text_preview: str) -> None:
        self._fan_out("agent_text", branch=branch, text_preview=text_preview)

    def agent_progress(self, *, branch: str, description: str) -> None:
        self._fan_out("agent_progress", branch=branch, description=description)

    def agent_error(self, *, branch: str, error: str) -> None:
        self._fan_out("agent_error", branch=branch, error=error)

    def crash_recovery_started(self, *, stale_agent_count: int) -> None:
        self._fan_out("crash_recovery_started", stale_agent_count=stale_agent_count)

    def composer_rebuilt(self, *, template_count: int) -> None:
        self._fan_out("composer_rebuilt", template_count=template_count)

    def composer_rebuild_failed(self, *, reason: str) -> None:
        self._fan_out("composer_rebuild_failed", reason=reason)

    def plan_synced(self, *, cycle: int) -> None:
        self._fan_out("plan_synced", cycle=cycle)
