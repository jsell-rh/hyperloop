from __future__ import annotations

import structlog

from hyperloop.reconciliation.ports.observer import ChangeType


_WARNING_EVENTS = frozenset(
    {
        "decomposition_failed",
        "task_failed",
        "dependency_invalidated",
        "task_merge_conflict",
        "verification_launch_failed",
        "verification_failed",
        "spec_failed",
        "trunk_integration_failed",
        "delivery_rebase_failed",
        "agent_launch_failed",
        "stale_agent_detected",
        "composer_rebuild_failed",
    }
)


class StructlogObserver:
    def __init__(self) -> None:
        self._logger: structlog.stdlib.BoundLogger = structlog.get_logger()

    _DEBUG_EVENTS = frozenset(
        {
            "agent_tool_use",
            "agent_text",
            "agent_progress",
            "agent_error",
        }
    )

    def _emit(self, event: str, **kwargs: object) -> None:
        if event in _WARNING_EVENTS:
            self._logger.warning(event, **kwargs)
        elif event in self._DEBUG_EVENTS:
            self._logger.debug(event, **kwargs)
        else:
            self._logger.info(event, **kwargs)

    def reconciler_started(self, *, spec_count: int, cycle: int) -> None:
        self._emit("reconciler_started", spec_count=spec_count, cycle=cycle)

    def reconciler_halted(self, *, reason: str, total_cycles: int) -> None:
        self._emit("reconciler_halted", reason=reason, total_cycles=total_cycles)

    def cycle_started(
        self, *, cycle: int, specs_out_of_sync: int, tasks_in_progress: int
    ) -> None:
        self._emit(
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
        self._emit(
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
        self._emit(
            "spec_divergence_detected",
            spec_path=spec_path,
            blob_sha=blob_sha,
            change_type=change_type,
        )

    def spec_superseded(self, *, spec_path: str, old_sha: str, new_sha: str) -> None:
        self._emit(
            "spec_superseded", spec_path=spec_path, old_sha=old_sha, new_sha=new_sha
        )

    def decomposition_started(self, *, specs_count: int, cycle: int) -> None:
        self._emit("decomposition_started", specs_count=specs_count, cycle=cycle)

    def decomposition_completed(
        self, *, specs_count: int, tasks_created: int, cycle: int, duration_s: float
    ) -> None:
        self._emit(
            "decomposition_completed",
            specs_count=specs_count,
            tasks_created=tasks_created,
            cycle=cycle,
            duration_s=duration_s,
        )

    def decomposition_failed(self, *, reason: str, cycle: int) -> None:
        self._emit("decomposition_failed", reason=reason, cycle=cycle)

    def task_created(
        self,
        *,
        task_id: int,
        spec_path: str,
        spec_blob_sha: str,
        name: str,
        depends_on: list[int],
    ) -> None:
        self._emit(
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
        self._emit(
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
        self._emit(
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
        self._emit(
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
        self._emit(
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
        self._emit(
            "dependency_invalidated",
            task_id=task_id,
            spec_path=spec_path,
            dependency_task_id=dependency_task_id,
            reason=reason,
        )

    def task_merge_completed(self, *, task_id: int, spec_blob_sha: str) -> None:
        self._emit("task_merge_completed", task_id=task_id, spec_blob_sha=spec_blob_sha)

    def task_merge_conflict(self, *, task_id: int, spec_blob_sha: str) -> None:
        self._emit("task_merge_conflict", task_id=task_id, spec_blob_sha=spec_blob_sha)

    def merge_resolution_launched(self, *, task_id: int, spec_blob_sha: str) -> None:
        self._emit(
            "merge_resolution_launched", task_id=task_id, spec_blob_sha=spec_blob_sha
        )

    def merge_resolution_completed(
        self, *, task_id: int, spec_blob_sha: str, success: bool
    ) -> None:
        self._emit(
            "merge_resolution_completed",
            task_id=task_id,
            spec_blob_sha=spec_blob_sha,
            success=success,
        )

    def trunk_integration_started(
        self, *, spec_path: str, spec_blob_sha: str, integration_id: str
    ) -> None:
        self._emit(
            "trunk_integration_started",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            integration_id=integration_id,
        )

    def trunk_integration_completed(
        self, *, spec_path: str, spec_blob_sha: str, integration_id: str
    ) -> None:
        self._emit(
            "trunk_integration_completed",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            integration_id=integration_id,
        )

    def trunk_integration_failed(
        self, *, spec_path: str, spec_blob_sha: str, reason: str
    ) -> None:
        self._emit(
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
        self._emit(
            "integration_polled",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            integration_id=integration_id,
            status=status,
        )

    def delivery_rebase_started(self, *, spec_path: str, spec_blob_sha: str) -> None:
        self._emit(
            "delivery_rebase_started",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
        )

    def delivery_rebase_completed(self, *, spec_path: str, spec_blob_sha: str) -> None:
        self._emit(
            "delivery_rebase_completed",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
        )

    def delivery_rebase_failed(
        self, *, spec_path: str, spec_blob_sha: str, reason: str
    ) -> None:
        self._emit(
            "delivery_rebase_failed",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            reason=reason,
        )

    def verification_launched(
        self, *, spec_path: str, spec_blob_sha: str, cycle: int
    ) -> None:
        self._emit(
            "verification_launched",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            cycle=cycle,
        )

    def verification_launch_failed(
        self, *, spec_path: str, spec_blob_sha: str, reason: str, cycle: int
    ) -> None:
        self._emit(
            "verification_launch_failed",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            reason=reason,
            cycle=cycle,
        )

    def verification_passed(
        self, *, spec_path: str, spec_blob_sha: str, rationale: str, cycle: int
    ) -> None:
        self._emit(
            "verification_passed",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            rationale=rationale,
            cycle=cycle,
        )

    def verification_failed(
        self, *, spec_path: str, spec_blob_sha: str, rationale: str, cycle: int
    ) -> None:
        self._emit(
            "verification_failed",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            rationale=rationale,
            cycle=cycle,
        )

    def spec_synced(
        self, *, spec_path: str, spec_blob_sha: str, total_tasks: int, cycle: int
    ) -> None:
        self._emit(
            "spec_synced",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            total_tasks=total_tasks,
            cycle=cycle,
        )

    def spec_failed(
        self, *, spec_path: str, spec_blob_sha: str, reason: str, cycle: int
    ) -> None:
        self._emit(
            "spec_failed",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            reason=reason,
            cycle=cycle,
        )

    def redecomposition_triggered(
        self, *, spec_path: str, spec_blob_sha: str, failed_task_count: int, cycle: int
    ) -> None:
        self._emit(
            "redecomposition_triggered",
            spec_path=spec_path,
            spec_blob_sha=spec_blob_sha,
            failed_task_count=failed_task_count,
            cycle=cycle,
        )

    def agent_cancelled(self, *, task_id: int, spec_path: str, reason: str) -> None:
        self._emit(
            "agent_cancelled", task_id=task_id, spec_path=spec_path, reason=reason
        )

    def stale_agent_detected(self, *, task_id: int, spec_path: str) -> None:
        self._emit("stale_agent_detected", task_id=task_id, spec_path=spec_path)

    def agent_launch_failed(
        self, *, task_id: int, role: str, reason: str, cycle: int
    ) -> None:
        self._emit(
            "agent_launch_failed",
            task_id=task_id,
            role=role,
            reason=reason,
            cycle=cycle,
        )

    def crash_recovery_started(self, *, stale_agent_count: int) -> None:
        self._emit("crash_recovery_started", stale_agent_count=stale_agent_count)

    def composer_rebuilt(self, *, template_count: int) -> None:
        self._emit("composer_rebuilt", template_count=template_count)

    def composer_rebuild_failed(self, *, reason: str) -> None:
        self._emit("composer_rebuild_failed", reason=reason)

    def agent_tool_use(self, *, branch: str, tool: str, input_preview: str) -> None:
        self._emit("agent_tool_use", branch=branch, tool=tool, input=input_preview)

    def agent_text(self, *, branch: str, text_preview: str) -> None:
        self._emit("agent_text", branch=branch, text=text_preview)

    def agent_progress(self, *, branch: str, description: str) -> None:
        self._emit("agent_progress", branch=branch, description=description)

    def agent_error(self, *, branch: str, error: str) -> None:
        self._emit("agent_error", branch=branch, error=error)

    def plan_synced(self, *, cycle: int) -> None:
        self._emit("plan_synced", cycle=cycle)
