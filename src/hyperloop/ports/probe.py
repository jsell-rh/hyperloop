"""OrchestratorProbe port — domain probe interface for observability.

One method per interesting moment. All methods use keyword-only arguments
so call sites are self-documenting and adding new keyword args is non-breaking.

Implementations: NullProbe, MultiProbe (adapters/probe/base.py),
StructlogProbe (adapters/probe/structlog.py),
MatrixProbe (adapters/probe/matrix.py),
RecordingProbe (tests/fakes/probe.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from hyperloop.domain.model import PromptSection


class OrchestratorProbe(Protocol):
    """Domain probe interface — one method per interesting moment.

    All methods are keyword-only after the first positional argument (self).
    This makes call sites self-documenting and makes adding new keyword args
    non-breaking for existing adapters that don't care about the new field.

    Contract: implementations must not raise. Probe failures must not
    propagate into the orchestrator loop.
    """

    # ------------------------------------------------------------------
    # Orchestrator lifecycle
    # ------------------------------------------------------------------

    def orchestrator_started(
        self,
        *,
        task_count: int,
        max_workers: int,
        max_task_rounds: int,
    ) -> None:
        """Orchestrator loop began, after recovery."""
        ...

    def orchestrator_halted(
        self,
        *,
        reason: str,
        total_cycles: int,
        completed_tasks: int,
        failed_tasks: int,
    ) -> None:
        """Loop exited — convergence or error."""
        ...

    # ------------------------------------------------------------------
    # Cycle
    # ------------------------------------------------------------------

    def cycle_started(
        self,
        *,
        cycle: int,
        active_workers: int,
        not_started: int,
        in_progress: int,
        completed: int,
        failed: int,
    ) -> None:
        """Serial section began."""
        ...

    def cycle_completed(
        self,
        *,
        cycle: int,
        active_workers: int,
        not_started: int,
        in_progress: int,
        completed: int,
        failed: int,
        spawned_ids: tuple[str, ...],
        reaped_ids: tuple[str, ...],
        duration_s: float,
    ) -> None:
        """Serial section finished. Replaces the on_cycle callback."""
        ...

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------

    def worker_spawned(
        self,
        *,
        task_id: str,
        role: str,
        branch: str,
        round: int,
        cycle: int,
        spec_ref: str,
    ) -> None:
        """Agent session started on a branch."""
        ...

    def worker_reaped(
        self,
        *,
        task_id: str,
        role: str,
        verdict: str,
        round: int,
        cycle: int,
        spec_ref: str,
        detail: str,
        duration_s: float,
    ) -> None:
        """Agent session completed and result collected."""
        ...

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    def task_advanced(
        self,
        *,
        task_id: str,
        spec_ref: str,
        from_phase: str | None,
        to_phase: str | None,
        from_status: str,
        to_status: str,
        round: int,
        cycle: int,
    ) -> None:
        """Task moved to a new pipeline phase or status."""
        ...

    def task_retried(
        self,
        *,
        task_id: str,
        spec_ref: str,
        round: int,
        cycle: int,
        findings_preview: str,
    ) -> None:
        """Verification failed, task restarting the pipeline loop."""
        ...

    def task_completed(
        self,
        *,
        task_id: str,
        spec_ref: str,
        total_rounds: int,
        total_cycles: int,
        cycle: int,
    ) -> None:
        """Task reached terminal success."""
        ...

    def task_failed(
        self,
        *,
        task_id: str,
        spec_ref: str,
        reason: str,
        round: int,
        cycle: int,
    ) -> None:
        """Task reached terminal failure (max_task_rounds or pipeline failure)."""
        ...

    def task_reset(
        self,
        *,
        task_id: str,
        spec_ref: str,
        reason: str,
        prior_round: int,
        cycle: int,
    ) -> None:
        """Task was reset to not-started due to a poisoned branch."""
        ...

    # ------------------------------------------------------------------
    # Pipeline: signals, merges, steps
    # ------------------------------------------------------------------

    def signal_checked(
        self,
        *,
        task_id: str,
        signal_name: str,
        status: str,
        message: str,
        cycle: int,
    ) -> None:
        """A signal was polled for a task."""
        ...

    def merge_attempted(
        self,
        *,
        task_id: str,
        branch: str,
        spec_ref: str,
        outcome: str,
        attempt: int,
        cycle: int,
    ) -> None:
        """PR merge was attempted (whether or not it succeeded)."""
        ...

    def step_executed(
        self,
        *,
        task_id: str,
        step_name: str,
        outcome: str,
        detail: str,
        cycle: int,
    ) -> None:
        """A pipeline step was executed."""
        ...

    # ------------------------------------------------------------------
    # Drift and convergence
    # ------------------------------------------------------------------

    def drift_detected(
        self,
        *,
        spec_path: str,
        drift_type: str,
        detail: str,
        cycle: int,
    ) -> None:
        """Drift was detected between spec and reality."""
        ...

    def convergence_marked(
        self,
        *,
        spec_path: str,
        spec_ref: str,
        cycle: int,
    ) -> None:
        """A spec was marked as converged."""
        ...

    # ------------------------------------------------------------------
    # Audit and GC
    # ------------------------------------------------------------------

    def reconcile_started(
        self,
        *,
        cycle: int,
    ) -> None:
        """Reconcile phase begun."""
        ...

    def reconcile_completed(
        self,
        *,
        cycle: int,
        duration_s: float,
        drift_count: int,
        audits_run: int,
        gc_pruned: int,
    ) -> None:
        """Reconcile phase ended with summary stats."""
        ...

    def auditors_started(
        self,
        *,
        count: int,
        cycle: int,
    ) -> None:
        """A batch of parallel auditors was launched."""
        ...

    def audit_started(
        self,
        *,
        spec_ref: str,
        cycle: int,
    ) -> None:
        """An individual auditor started for a spec."""
        ...

    def audit_ran(
        self,
        *,
        spec_ref: str,
        result: str,
        cycle: int,
        duration_s: float,
    ) -> None:
        """An audit check ran."""
        ...

    def gc_ran(
        self,
        *,
        pruned_count: int,
        cycle: int,
    ) -> None:
        """Garbage collection ran."""
        ...

    # ------------------------------------------------------------------
    # Serial agents
    # ------------------------------------------------------------------

    def intake_ran(
        self,
        *,
        unprocessed_specs: int,
        created_tasks: int,
        success: bool,
        cycle: int,
        duration_s: float,
    ) -> None:
        """PM intake agent ran."""
        ...

    def process_improver_ran(
        self,
        *,
        failed_task_ids: tuple[str, ...],
        success: bool,
        cycle: int,
        duration_s: float,
    ) -> None:
        """Process-improver agent ran after failures this cycle."""
        ...

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recovery_started(
        self,
        *,
        in_progress_tasks: int,
    ) -> None:
        """Orchestrator is recovering from a crash/restart."""
        ...

    def orphan_found(
        self,
        *,
        task_id: str,
        branch: str,
    ) -> None:
        """An orphaned worker was found and cancelled."""
        ...

    # ------------------------------------------------------------------
    # Worker crash detection
    # ------------------------------------------------------------------

    def worker_crash_detected(
        self,
        *,
        task_id: str,
        role: str,
        branch: str,
    ) -> None:
        """A worker crash was detected."""
        ...

    # ------------------------------------------------------------------
    # Prompt composition
    # ------------------------------------------------------------------

    def worker_message(
        self,
        *,
        task_id: str,
        role: str,
        message_type: str,
        content: str,
    ) -> None:
        """Individual message from a running worker (text, tool use, result).

        Emitted in real-time as the agent streams messages. Verbose-only
        in Matrix (thread reply under worker_spawned).
        """
        ...

    def spawn_failed(
        self,
        *,
        task_id: str,
        role: str,
        branch: str,
        attempt: int,
        max_attempts: int,
        cooldown_cycles: int,
        cycle: int,
    ) -> None:
        """Worker spawn failed. Retries remain or cooldown activated."""
        ...

    def prompt_composed(
        self,
        *,
        task_id: str,
        role: str,
        prompt_text: str,
        sections: tuple[PromptSection, ...],
        round: int,
        cycle: int,
    ) -> None:
        """Full composed prompt for a worker, for debugging/observability."""
        ...

    def pr_created(
        self,
        *,
        task_id: str,
        pr_url: str,
        branch: str,
    ) -> None:
        """A draft PR was created for a task."""
        ...

    def pr_marked_ready(
        self,
        *,
        pr_url: str,
    ) -> None:
        """A PR was marked as ready for review."""
        ...

    def feedback_checked(
        self,
        *,
        task_id: str,
        unprocessed_count: int,
        allowed_authors: tuple[str, ...],
        cycle: int,
    ) -> None:
        """Feedback was checked for unprocessed comments."""
        ...

    def agent_retried(
        self,
        *,
        role: str,
        operation: str,
        attempt: int,
        max_attempts: int,
        delay_s: float,
        error: str,
    ) -> None:
        """An agent operation failed transiently and will be retried."""
        ...

    def state_synced(self) -> None:
        """State was synced with remote (pull + push)."""
        ...
