"""FileProbe -- writes probe events as JSONL for the dashboard to read."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _serialize(v: object) -> object:
    """Convert a value to a JSON-safe type."""
    if isinstance(v, tuple):
        return [_serialize(item) for item in v]  # type: ignore[arg-type]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, list):
        return [_serialize(item) for item in v]  # type: ignore[arg-type]
    if isinstance(v, dict):
        return {str(k): _serialize(val) for k, val in v.items()}  # type: ignore[union-attr]
    if hasattr(v, "__dataclass_fields__"):
        import dataclasses

        return {
            k: _serialize(val)
            for k, val in dataclasses.asdict(v).items()  # type: ignore[arg-type]
        }
    return str(v)


class FileProbe:
    """Appends one JSON line per probe event to a file.

    The file path defaults to ~/.cache/hyperloop/{repo-hash}/events.jsonl.
    Truncates to max_events on startup.
    """

    def __init__(self, events_path: Path, max_events: int = 1000) -> None:
        self._path = events_path
        self._max_events = max_events
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._truncate_if_needed()

    def _truncate_if_needed(self) -> None:
        if not self._path.exists():
            return
        lines = self._path.read_text().strip().splitlines()
        if len(lines) > self._max_events:
            keep = lines[-self._max_events :]
            self._path.write_text("\n".join(keep) + "\n")

    def _write(self, event: str, **kwargs: object) -> None:
        entry: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "event": event,
            **{k: _serialize(v) for k, v in kwargs.items()},
        }
        with open(self._path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    # ------------------------------------------------------------------
    # Orchestrator lifecycle
    # ------------------------------------------------------------------

    def orchestrator_started(self, **kw: object) -> None:
        self._write("orchestrator_started", **kw)

    def orchestrator_halted(self, **kw: object) -> None:
        self._write("orchestrator_halted", **kw)

    # ------------------------------------------------------------------
    # Cycle
    # ------------------------------------------------------------------

    def cycle_started(self, **kw: object) -> None:
        self._write("cycle_started", **kw)

    def cycle_completed(self, **kw: object) -> None:
        self._write("cycle_completed", **kw)

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------

    def worker_spawned(self, **kw: object) -> None:
        self._write("worker_spawned", **kw)

    def worker_reaped(self, **kw: object) -> None:
        self._write("worker_reaped", **kw)

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    def task_advanced(self, **kw: object) -> None:
        self._write("task_advanced", **kw)

    def task_retried(self, **kw: object) -> None:
        self._write("task_retried", **kw)

    def task_completed(self, **kw: object) -> None:
        self._write("task_completed", **kw)

    def task_failed(self, **kw: object) -> None:
        self._write("task_failed", **kw)

    def task_reset(self, **kw: object) -> None:
        self._write("task_reset", **kw)

    # ------------------------------------------------------------------
    # Pipeline: signals, merges, steps
    # ------------------------------------------------------------------

    def signal_checked(self, **kw: object) -> None:
        self._write("signal_checked", **kw)

    def merge_attempted(self, **kw: object) -> None:
        self._write("merge_attempted", **kw)

    def step_executed(self, **kw: object) -> None:
        self._write("step_executed", **kw)

    # ------------------------------------------------------------------
    # Drift and convergence
    # ------------------------------------------------------------------

    def drift_detected(self, **kw: object) -> None:
        self._write("drift_detected", **kw)

    def convergence_marked(self, **kw: object) -> None:
        self._write("convergence_marked", **kw)

    # ------------------------------------------------------------------
    # Audit and GC
    # ------------------------------------------------------------------

    def audit_ran(self, **kw: object) -> None:
        self._write("audit_ran", **kw)

    def gc_ran(self, **kw: object) -> None:
        self._write("gc_ran", **kw)

    # ------------------------------------------------------------------
    # Serial agents
    # ------------------------------------------------------------------

    def intake_ran(self, **kw: object) -> None:
        self._write("intake_ran", **kw)

    def process_improver_ran(self, **kw: object) -> None:
        self._write("process_improver_ran", **kw)

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recovery_started(self, **kw: object) -> None:
        self._write("recovery_started", **kw)

    def orphan_found(self, **kw: object) -> None:
        self._write("orphan_found", **kw)

    # ------------------------------------------------------------------
    # Worker crash detection
    # ------------------------------------------------------------------

    def worker_crash_detected(self, **kw: object) -> None:
        self._write("worker_crash_detected", **kw)

    # ------------------------------------------------------------------
    # Worker messages
    # ------------------------------------------------------------------

    def worker_message(self, **kw: object) -> None:
        self._write("worker_message", **kw)

    def spawn_failed(self, **kw: object) -> None:
        self._write("spawn_failed", **kw)

    # ------------------------------------------------------------------
    # Prompt composition
    # ------------------------------------------------------------------

    def prompt_composed(self, **kw: object) -> None:
        self._write("prompt_composed", **kw)

    # ------------------------------------------------------------------
    # Git remote operations
    # ------------------------------------------------------------------

    def pr_created(self, **kw: object) -> None:
        self._write("pr_created", **kw)

    def pr_marked_ready(self, **kw: object) -> None:
        self._write("pr_marked_ready", **kw)

    def state_synced(self, **kw: object) -> None:
        self._write("state_synced", **kw)

    # ------------------------------------------------------------------
    # Backward-compatible aliases for call sites not yet migrated
    # ------------------------------------------------------------------

    def gate_checked(self, **kw: object) -> None:
        self._write("gate_checked", **kw)

    def task_looped_back(self, **kw: object) -> None:
        self._write("task_looped_back", **kw)

    def rebase_conflict(self, **kw: object) -> None:
        self._write("rebase_conflict", **kw)

    def intake_specs_detected(self, **kw: object) -> None:
        self._write("intake_specs_detected", **kw)

    def pr_label_changed(self, **kw: object) -> None:
        self._write("pr_label_changed", **kw)

    def branch_pushed(self, **kw: object) -> None:
        self._write("branch_pushed", **kw)
