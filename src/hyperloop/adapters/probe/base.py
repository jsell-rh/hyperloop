"""NullProbe and MultiProbe — foundational probe adapters.

NullProbe: discards all calls. Default when observability is not configured.
MultiProbe: fans out to N child probes, isolating exceptions per child.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from hyperloop.ports.probe import OrchestratorProbe

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


class NullProbe:
    """Discards all probe calls. Default when observability is not configured."""

    def orchestrator_started(self, **_: object) -> None:
        pass

    def orchestrator_halted(self, **_: object) -> None:
        pass

    def cycle_started(self, **_: object) -> None:
        pass

    def cycle_completed(self, **_: object) -> None:
        pass

    def worker_spawned(self, **_: object) -> None:
        pass

    def worker_reaped(self, **_: object) -> None:
        pass

    def task_advanced(self, **_: object) -> None:
        pass

    def task_retried(self, **_: object) -> None:
        pass

    def task_completed(self, **_: object) -> None:
        pass

    def task_failed(self, **_: object) -> None:
        pass

    def task_reset(self, **_: object) -> None:
        pass

    def signal_checked(self, **_: object) -> None:
        pass

    def merge_attempted(self, **_: object) -> None:
        pass

    def step_executed(self, **_: object) -> None:
        pass

    def drift_detected(self, **_: object) -> None:
        pass

    def convergence_marked(self, **_: object) -> None:
        pass

    def collect_started(self, **_: object) -> None:
        pass

    def collect_completed(self, **_: object) -> None:
        pass

    def advance_started(self, **_: object) -> None:
        pass

    def advance_completed(self, **_: object) -> None:
        pass

    def spawn_started(self, **_: object) -> None:
        pass

    def spawn_completed(self, **_: object) -> None:
        pass

    def reconcile_started(self, **_: object) -> None:
        pass

    def reconcile_completed(self, **_: object) -> None:
        pass

    def auditors_started(self, **_: object) -> None:
        pass

    def audit_started(self, **_: object) -> None:
        pass

    def audit_ran(self, **_: object) -> None:
        pass

    def gc_ran(self, **_: object) -> None:
        pass

    def intake_ran(self, **_: object) -> None:
        pass

    def process_improver_ran(self, **_: object) -> None:
        pass

    def recovery_started(self, **_: object) -> None:
        pass

    def orphan_found(self, **_: object) -> None:
        pass

    def worker_crash_detected(self, **_: object) -> None:
        pass

    def worker_message(self, **_: object) -> None:
        pass

    def spawn_failed(self, **_: object) -> None:
        pass

    def prompt_composed(self, **_: object) -> None:
        pass

    def pr_created(self, **_: object) -> None:
        pass

    def pr_marked_ready(self, **_: object) -> None:
        pass

    def feedback_checked(self, **_: object) -> None:
        pass

    def agent_retried(self, **_: object) -> None:
        pass

    def state_synced(self, **_: object) -> None:
        pass

    def state_sync_failed(self, **_: object) -> None:
        pass

    def trunk_push_failed(self, **_: object) -> None:
        pass


class MultiProbe:
    """Fans out all probe calls to N child probes.

    Isolates each child: an exception in one child is logged and swallowed
    so other children still receive the call.
    """

    def __init__(self, probes: tuple[OrchestratorProbe, ...]) -> None:
        self._probes = probes

    def _call(self, method: str, **kwargs: object) -> None:
        for probe in self._probes:
            try:
                getattr(probe, method)(**kwargs)
            except Exception:
                logger.exception("Probe error in %s.%s", type(probe).__name__, method)

    def orchestrator_started(self, **kw: object) -> None:
        self._call("orchestrator_started", **kw)

    def orchestrator_halted(self, **kw: object) -> None:
        self._call("orchestrator_halted", **kw)

    def cycle_started(self, **kw: object) -> None:
        self._call("cycle_started", **kw)

    def cycle_completed(self, **kw: object) -> None:
        self._call("cycle_completed", **kw)

    def worker_spawned(self, **kw: object) -> None:
        self._call("worker_spawned", **kw)

    def worker_reaped(self, **kw: object) -> None:
        self._call("worker_reaped", **kw)

    def task_advanced(self, **kw: object) -> None:
        self._call("task_advanced", **kw)

    def task_retried(self, **kw: object) -> None:
        self._call("task_retried", **kw)

    def task_completed(self, **kw: object) -> None:
        self._call("task_completed", **kw)

    def task_failed(self, **kw: object) -> None:
        self._call("task_failed", **kw)

    def task_reset(self, **kw: object) -> None:
        self._call("task_reset", **kw)

    def signal_checked(self, **kw: object) -> None:
        self._call("signal_checked", **kw)

    def merge_attempted(self, **kw: object) -> None:
        self._call("merge_attempted", **kw)

    def step_executed(self, **kw: object) -> None:
        self._call("step_executed", **kw)

    def drift_detected(self, **kw: object) -> None:
        self._call("drift_detected", **kw)

    def convergence_marked(self, **kw: object) -> None:
        self._call("convergence_marked", **kw)

    def collect_started(self, **kw: object) -> None:
        self._call("collect_started", **kw)

    def collect_completed(self, **kw: object) -> None:
        self._call("collect_completed", **kw)

    def advance_started(self, **kw: object) -> None:
        self._call("advance_started", **kw)

    def advance_completed(self, **kw: object) -> None:
        self._call("advance_completed", **kw)

    def spawn_started(self, **kw: object) -> None:
        self._call("spawn_started", **kw)

    def spawn_completed(self, **kw: object) -> None:
        self._call("spawn_completed", **kw)

    def reconcile_started(self, **kw: object) -> None:
        self._call("reconcile_started", **kw)

    def reconcile_completed(self, **kw: object) -> None:
        self._call("reconcile_completed", **kw)

    def auditors_started(self, **kw: object) -> None:
        self._call("auditors_started", **kw)

    def audit_started(self, **kw: object) -> None:
        self._call("audit_started", **kw)

    def audit_ran(self, **kw: object) -> None:
        self._call("audit_ran", **kw)

    def gc_ran(self, **kw: object) -> None:
        self._call("gc_ran", **kw)

    def intake_ran(self, **kw: object) -> None:
        self._call("intake_ran", **kw)

    def process_improver_ran(self, **kw: object) -> None:
        self._call("process_improver_ran", **kw)

    def recovery_started(self, **kw: object) -> None:
        self._call("recovery_started", **kw)

    def orphan_found(self, **kw: object) -> None:
        self._call("orphan_found", **kw)

    def worker_crash_detected(self, **kw: object) -> None:
        self._call("worker_crash_detected", **kw)

    def worker_message(self, **kw: object) -> None:
        self._call("worker_message", **kw)

    def spawn_failed(self, **kw: object) -> None:
        self._call("spawn_failed", **kw)

    def prompt_composed(self, **kw: object) -> None:
        self._call("prompt_composed", **kw)

    def pr_created(self, **kw: object) -> None:
        self._call("pr_created", **kw)

    def pr_marked_ready(self, **kw: object) -> None:
        self._call("pr_marked_ready", **kw)

    def feedback_checked(self, **kw: object) -> None:
        self._call("feedback_checked", **kw)

    def agent_retried(self, **kw: object) -> None:
        self._call("agent_retried", **kw)

    def state_synced(self, **kw: object) -> None:
        self._call("state_synced", **kw)

    def state_sync_failed(self, **kw: object) -> None:
        self._call("state_sync_failed", **kw)

    def trunk_push_failed(self, **kw: object) -> None:
        self._call("trunk_push_failed", **kw)
