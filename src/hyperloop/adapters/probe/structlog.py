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

    def task_looped_back(self, **kw: object) -> None:
        self._log.warning("task_looped_back", **kw)

    def task_completed(self, **kw: object) -> None:
        self._log.info("task_completed", **kw)

    def task_failed(self, **kw: object) -> None:
        self._log.error("task_failed", **kw)

    # ------------------------------------------------------------------
    # Pipeline: gates, merges, conflicts
    # ------------------------------------------------------------------

    def gate_checked(self, **kw: object) -> None:
        cleared = kw.get("cleared", False)
        level = "info" if cleared else "debug"
        getattr(self._log, level)("gate_checked", **kw)

    def merge_attempted(self, **kw: object) -> None:
        outcome = kw.get("outcome")
        level = "info" if outcome == "merged" else "warning"
        getattr(self._log, level)("merge_attempted", **kw)

    def rebase_conflict(self, **kw: object) -> None:
        self._log.warning("rebase_conflict", **kw)

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
    # Prompt composition
    # ------------------------------------------------------------------

    def prompt_composed(self, **kw: object) -> None:
        self._log.debug("prompt_composed", **kw)
