"""StructlogProbe — translates probe calls into structured log entries.

Each probe method becomes a single structlog log line. The method name is the
event string; all keyword arguments become structlog bound keys. Log levels
follow the mapping table in specs/observability.md.
"""

from __future__ import annotations

import structlog


class StructlogProbe:
    """Emits structured log entries for every probe call.

    Constructor accepts ``log_format`` and ``log_level`` for documentation
    symmetry with ``configure_logging``, but does **not** call it — logging
    configuration is done once externally at startup.
    """

    def __init__(self, log_format: str = "console", log_level: str = "info") -> None:
        self._log: structlog.stdlib.BoundLogger = structlog.get_logger()

    # ------------------------------------------------------------------
    # Orchestrator lifecycle
    # ------------------------------------------------------------------

    def orchestrator_started(self, **kw: object) -> None:
        self._log.info("orchestrator_started", **kw)

    def orchestrator_halted(self, **kw: object) -> None:
        reason = kw.get("reason", "")
        level = "info" if isinstance(reason, str) and "complete" in reason else "error"
        getattr(self._log, level)("orchestrator_halted", **kw)

    # ------------------------------------------------------------------
    # Cycle
    # ------------------------------------------------------------------

    def cycle_started(self, *, cycle: int, **kw: object) -> None:
        self._log = self._log.bind(cycle=cycle)
        self._log.debug("cycle_started", **kw)

    def cycle_completed(self, **kw: object) -> None:
        duration_s = kw.get("duration_s")
        if isinstance(duration_s, float):
            kw = {**kw, "duration_s": round(duration_s, 1)}
        self._log.info("cycle_completed", **kw)

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------

    def worker_spawned(self, **kw: object) -> None:
        self._log.debug("worker_spawned", **kw)

    def worker_reaped(self, **kw: object) -> None:
        verdict = kw.get("verdict")
        level = "info" if verdict == "pass" else "warning"
        duration_s = kw.get("duration_s")
        if isinstance(duration_s, float):
            kw = {**kw, "duration_s": round(duration_s, 1)}
        # Strip None-valued runtime metrics to keep log lines clean
        kw = {k: v for k, v in kw.items() if v is not None}
        getattr(self._log, level)("worker_reaped", **kw)

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    def task_advanced(self, **kw: object) -> None:
        self._log.debug("task_advanced", **kw)

    def task_retried(self, **kw: object) -> None:
        self._log.warning("task_retried", **kw)

    def task_completed(self, **kw: object) -> None:
        self._log.info("task_completed", **kw)

    def task_failed(self, **kw: object) -> None:
        self._log.error("task_failed", **kw)

    def task_reset(self, **kw: object) -> None:
        self._log.warning("task_reset", **kw)

    # ------------------------------------------------------------------
    # Pipeline: signals, merges, steps
    # ------------------------------------------------------------------

    def signal_checked(self, **kw: object) -> None:
        status = kw.get("status", "")
        level = "debug" if status == "pending" else "info"
        getattr(self._log, level)("signal_checked", **kw)

    def merge_attempted(self, **kw: object) -> None:
        outcome = kw.get("outcome")
        level = "info" if outcome == "merged" else "warning"
        getattr(self._log, level)("merge_attempted", **kw)

    def step_executed(self, **kw: object) -> None:
        self._log.debug("step_executed", **kw)

    # ------------------------------------------------------------------
    # Drift and convergence
    # ------------------------------------------------------------------

    def drift_detected(self, **kw: object) -> None:
        self._log.info("drift_detected", **kw)

    def convergence_marked(self, **kw: object) -> None:
        self._log.info("convergence_marked", **kw)

    # ------------------------------------------------------------------
    # Phase timing
    # ------------------------------------------------------------------

    def collect_started(self, **kw: object) -> None:
        self._log.debug("collect_started", **kw)

    def collect_completed(self, **kw: object) -> None:
        duration_s = kw.get("duration_s")
        if isinstance(duration_s, float):
            kw = {**kw, "duration_s": round(duration_s, 3)}
        self._log.debug("collect_completed", **kw)

    def advance_started(self, **kw: object) -> None:
        self._log.debug("advance_started", **kw)

    def advance_completed(self, **kw: object) -> None:
        duration_s = kw.get("duration_s")
        if isinstance(duration_s, float):
            kw = {**kw, "duration_s": round(duration_s, 3)}
        self._log.debug("advance_completed", **kw)

    def spawn_started(self, **kw: object) -> None:
        self._log.debug("spawn_started", **kw)

    def spawn_completed(self, **kw: object) -> None:
        duration_s = kw.get("duration_s")
        if isinstance(duration_s, float):
            kw = {**kw, "duration_s": round(duration_s, 3)}
        self._log.debug("spawn_completed", **kw)

    # ------------------------------------------------------------------
    # Audit and GC
    # ------------------------------------------------------------------

    def reconcile_started(self, **kw: object) -> None:
        self._log.info("reconcile_started", **kw)

    def reconcile_completed(self, **kw: object) -> None:
        duration_s = kw.get("duration_s")
        if isinstance(duration_s, float):
            kw = {**kw, "duration_s": round(duration_s, 1)}
        self._log.info("reconcile_completed", **kw)

    def auditors_started(self, **kw: object) -> None:
        self._log.info("auditors_started", **kw)

    def audit_started(self, **kw: object) -> None:
        self._log.info("audit_started", **kw)

    def audit_ran(self, **kw: object) -> None:
        duration_s = kw.get("duration_s")
        if isinstance(duration_s, float):
            kw = {**kw, "duration_s": round(duration_s, 1)}
        self._log.info("audit_ran", **kw)

    def gc_ran(self, **kw: object) -> None:
        self._log.info("gc_ran", **kw)

    # ------------------------------------------------------------------
    # Serial agents
    # ------------------------------------------------------------------

    def intake_ran(self, **kw: object) -> None:
        duration_s = kw.get("duration_s")
        if isinstance(duration_s, float):
            kw = {**kw, "duration_s": round(duration_s, 1)}
        self._log.info("intake_ran", **kw)

    def process_improver_ran(self, **kw: object) -> None:
        duration_s = kw.get("duration_s")
        if isinstance(duration_s, float):
            kw = {**kw, "duration_s": round(duration_s, 1)}
        self._log.info("process_improver_ran", **kw)

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recovery_started(self, **kw: object) -> None:
        self._log.info("recovery_started", **kw)

    def orphan_found(self, **kw: object) -> None:
        self._log.warning("orphan_found", **kw)

    # ------------------------------------------------------------------
    # Worker crash detection
    # ------------------------------------------------------------------

    def worker_crash_detected(self, **kw: object) -> None:
        self._log.warning("worker_crash_detected", **kw)

    # ------------------------------------------------------------------
    # Worker messages
    # ------------------------------------------------------------------

    def worker_message(self, **kw: object) -> None:
        self._log.debug("worker_message", **kw)

    def spawn_failed(self, **kw: object) -> None:
        self._log.warning("spawn_failed", **kw)

    # ------------------------------------------------------------------
    # Prompt composition
    # ------------------------------------------------------------------

    def prompt_composed(self, **kw: object) -> None:
        sections = kw.pop("sections", ())
        section_sources: list[str] = []
        if isinstance(sections, (tuple, list)):
            section_sources = [
                str(getattr(s, "source", str(s)))  # type: ignore[arg-type]
                for s in sections  # type: ignore[union-attr]
            ]
        kw_out = {
            **kw,
            "section_count": len(section_sources),
            "section_sources": section_sources,
        }
        self._log.debug("prompt_composed", **kw_out)

    # ------------------------------------------------------------------
    # Git remote operations
    # ------------------------------------------------------------------

    def pr_created(self, **kw: object) -> None:
        self._log.info("pr_created", **kw)

    def pr_marked_ready(self, **kw: object) -> None:
        self._log.debug("pr_marked_ready", **kw)

    def feedback_checked(self, **kw: object) -> None:
        self._log.info("feedback_checked", **kw)

    def agent_retried(self, **kw: object) -> None:
        self._log.warning("agent_retried", **kw)

    def state_synced(self, **kw: object) -> None:
        self._log.debug("state_synced", **kw)

    def state_sync_failed(self, **kw: object) -> None:
        self._log.warning("state_sync_failed", **kw)

    def trunk_push_failed(self, **kw: object) -> None:
        self._log.warning("trunk_push_failed", **kw)
