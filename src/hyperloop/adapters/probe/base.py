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

    def task_looped_back(self, **_: object) -> None:
        pass

    def task_completed(self, **_: object) -> None:
        pass

    def task_failed(self, **_: object) -> None:
        pass

    def gate_checked(self, **_: object) -> None:
        pass

    def merge_attempted(self, **_: object) -> None:
        pass

    def rebase_conflict(self, **_: object) -> None:
        pass

    def intake_ran(self, **_: object) -> None:
        pass

    def process_improver_ran(self, **_: object) -> None:
        pass

    def recovery_started(self, **_: object) -> None:
        pass

    def orphan_found(self, **_: object) -> None:
        pass

    def worker_message(self, **_: object) -> None:
        pass

    def spawn_failed(self, **_: object) -> None:
        pass

    def prompt_composed(self, **_: object) -> None:
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

    def task_looped_back(self, **kw: object) -> None:
        self._call("task_looped_back", **kw)

    def task_completed(self, **kw: object) -> None:
        self._call("task_completed", **kw)

    def task_failed(self, **kw: object) -> None:
        self._call("task_failed", **kw)

    def gate_checked(self, **kw: object) -> None:
        self._call("gate_checked", **kw)

    def merge_attempted(self, **kw: object) -> None:
        self._call("merge_attempted", **kw)

    def rebase_conflict(self, **kw: object) -> None:
        self._call("rebase_conflict", **kw)

    def intake_ran(self, **kw: object) -> None:
        self._call("intake_ran", **kw)

    def process_improver_ran(self, **kw: object) -> None:
        self._call("process_improver_ran", **kw)

    def recovery_started(self, **kw: object) -> None:
        self._call("recovery_started", **kw)

    def orphan_found(self, **kw: object) -> None:
        self._call("orphan_found", **kw)

    def worker_message(self, **kw: object) -> None:
        self._call("worker_message", **kw)

    def spawn_failed(self, **kw: object) -> None:
        self._call("spawn_failed", **kw)

    def prompt_composed(self, **kw: object) -> None:
        self._call("prompt_composed", **kw)
