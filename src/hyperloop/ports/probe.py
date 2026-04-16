"""OrchestratorProbe port — domain probe interface for observability.

One method per interesting moment. All methods use keyword-only arguments
so call sites are self-documenting and adding new keyword args is non-breaking.

Implementations: NullProbe, MultiProbe (adapters/probe.py),
StructlogProbe (adapters/structlog_probe.py),
MatrixProbe (adapters/matrix_probe.py),
RecordingProbe (tests/fakes/probe.py).
"""

from __future__ import annotations

from typing import Protocol


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
        complete: int,
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
        complete: int,
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
        findings_count: int,
        detail: str,
        duration_s: float,
        cost_usd: float | None = None,
        num_turns: int | None = None,
        api_duration_ms: float | None = None,
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

    def task_looped_back(
        self,
        *,
        task_id: str,
        spec_ref: str,
        round: int,
        cycle: int,
        findings_preview: str,
        findings_count: int,
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

    # ------------------------------------------------------------------
    # Pipeline: gates, merges, conflicts
    # ------------------------------------------------------------------

    def gate_checked(
        self,
        *,
        task_id: str,
        gate: str,
        cleared: bool,
        cycle: int,
    ) -> None:
        """A gate was polled for a task."""
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

    def rebase_conflict(
        self,
        *,
        task_id: str,
        branch: str,
        attempt: int,
        max_attempts: int,
        looping_back: bool,
        cycle: int,
    ) -> None:
        """Rebase failed; task deferred or sent back through pipeline."""
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

    def prompt_composed(
        self,
        *,
        task_id: str,
        role: str,
        prompt_text: str,
        round: int,
        cycle: int,
    ) -> None:
        """Full composed prompt for a worker, for debugging/observability."""
        ...
