"""RecordingProbe — test fake that captures all probe calls for assertions.

A first-class fake, tested via contract tests, reusable across all tests.
Matches the OrchestratorProbe protocol defined in src/hyperloop/ports/probe.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RecordedCall:
    """A single recorded probe call."""

    method: str
    kwargs: dict[str, object] = field(default_factory=lambda: {})


class RecordingProbe:
    """Captures all probe calls for test assertions. No output."""

    def __init__(self) -> None:
        self.calls: list[RecordedCall] = []

    def _record(self, method: str, **kwargs: object) -> None:
        self.calls.append(RecordedCall(method=method, kwargs=dict(kwargs)))

    def of_method(self, method: str) -> list[dict[str, object]]:
        """Return kwargs of all calls to the named method."""
        return [c.kwargs for c in self.calls if c.method == method]

    def last(self, method: str) -> dict[str, object]:
        """Return kwargs of the most recent call to the named method."""
        calls = self.of_method(method)
        if not calls:
            raise AssertionError(f"No calls to {method!r}")
        return calls[-1]

    # ------------------------------------------------------------------
    # Orchestrator lifecycle
    # ------------------------------------------------------------------

    def orchestrator_started(self, **kw: object) -> None:
        self._record("orchestrator_started", **kw)

    def orchestrator_halted(self, **kw: object) -> None:
        self._record("orchestrator_halted", **kw)

    # ------------------------------------------------------------------
    # Cycle
    # ------------------------------------------------------------------

    def cycle_started(self, **kw: object) -> None:
        self._record("cycle_started", **kw)

    def cycle_completed(self, **kw: object) -> None:
        self._record("cycle_completed", **kw)

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------

    def worker_spawned(self, **kw: object) -> None:
        self._record("worker_spawned", **kw)

    def worker_reaped(self, **kw: object) -> None:
        self._record("worker_reaped", **kw)

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    def task_advanced(self, **kw: object) -> None:
        self._record("task_advanced", **kw)

    def task_retried(self, **kw: object) -> None:
        self._record("task_retried", **kw)

    def task_completed(self, **kw: object) -> None:
        self._record("task_completed", **kw)

    def task_failed(self, **kw: object) -> None:
        self._record("task_failed", **kw)

    def task_reset(self, **kw: object) -> None:
        self._record("task_reset", **kw)

    # ------------------------------------------------------------------
    # Pipeline: signals, merges
    # ------------------------------------------------------------------

    def signal_checked(self, **kw: object) -> None:
        self._record("signal_checked", **kw)

    def merge_attempted(self, **kw: object) -> None:
        self._record("merge_attempted", **kw)

    # ------------------------------------------------------------------
    # Serial agents
    # ------------------------------------------------------------------

    def intake_ran(self, **kw: object) -> None:
        self._record("intake_ran", **kw)

    def process_improver_ran(self, **kw: object) -> None:
        self._record("process_improver_ran", **kw)

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recovery_started(self, **kw: object) -> None:
        self._record("recovery_started", **kw)

    def orphan_found(self, **kw: object) -> None:
        self._record("orphan_found", **kw)

    # ------------------------------------------------------------------
    # Prompt composition & misc
    # ------------------------------------------------------------------

    def worker_message(self, **kw: object) -> None:
        self._record("worker_message", **kw)

    def spawn_failed(self, **kw: object) -> None:
        self._record("spawn_failed", **kw)

    def prompt_composed(self, **kw: object) -> None:
        self._record("prompt_composed", **kw)

    def pr_created(self, **kw: object) -> None:
        self._record("pr_created", **kw)

    def pr_marked_ready(self, **kw: object) -> None:
        self._record("pr_marked_ready", **kw)

    def state_synced(self, **kw: object) -> None:
        self._record("state_synced", **kw)

    # ------------------------------------------------------------------
    # Reconciler lifecycle
    # ------------------------------------------------------------------

    def drift_detected(self, **kw: object) -> None:
        self._record("drift_detected", **kw)

    def audit_ran(self, **kw: object) -> None:
        self._record("audit_ran", **kw)

    def gc_ran(self, **kw: object) -> None:
        self._record("gc_ran", **kw)

    def convergence_marked(self, **kw: object) -> None:
        self._record("convergence_marked", **kw)

    def worker_crash_detected(self, **kw: object) -> None:
        self._record("worker_crash_detected", **kw)

    def step_executed(self, **kw: object) -> None:
        self._record("step_executed", **kw)

    # ------------------------------------------------------------------
    # Deprecated — kept for backward compatibility during migration.
    # Production code still calls these; remove once callers are updated.
    # ------------------------------------------------------------------

    def task_looped_back(self, **kw: object) -> None:
        self._record("task_looped_back", **kw)

    def gate_checked(self, **kw: object) -> None:
        self._record("gate_checked", **kw)

    def rebase_conflict(self, **kw: object) -> None:
        self._record("rebase_conflict", **kw)

    def intake_specs_detected(self, **kw: object) -> None:
        self._record("intake_specs_detected", **kw)

    def pr_label_changed(self, **kw: object) -> None:
        self._record("pr_label_changed", **kw)

    def branch_pushed(self, **kw: object) -> None:
        self._record("branch_pushed", **kw)
