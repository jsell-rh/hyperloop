# Domain-Oriented Observability

The orchestrator needs structured, queryable observability that follows the domain — not scattered `logger.info` calls that couple instrumentation to implementation details.

The approach: **domain probes** declare what's interesting as typed method signatures. Probe implementations decide how to ship the signal. Adding context to an existing probe point is a one-line keyword-argument addition. No dataclass edits, no observer dispatch rewiring, no format string hunting.

## Why Probes, Not Events

An event-object design (`emit(WorkerReaped(...))`) looks clean on paper but creates friction in practice:

- Adding a field to an existing event means editing the dataclass, the emit site, and every adapter's formatting/dispatch logic — three files minimum.
- Adapters dispatch on event type with `isinstance` chains or a union match. Adding a new event type touches the union, the dispatch, and every adapter.
- Events are stateless snapshots. They can't carry derived context like duration (which requires knowing when the worker was spawned).

The probe pattern solves all three:

- **Adding a field** = add a keyword argument to the method signature. The protocol and all implementations update in one pass. Callers that don't supply it get a type error immediately.
- **Adding a probe point** = add a method. No dispatch, no union, no registration.
- **Duration** = the probe implementation records `spawned_at` when `worker_spawned` is called and computes elapsed when `worker_reaped` is called. Timing is an adapter concern, invisible to the domain.

## Principles

1. **The probe interface is the schema.** Method signatures with keyword-only arguments define exactly what attributes exist, what types they have, and what name they carry. No string-key drift. No `Optional[str]` sprawl from trying to unify unrelated events into a shared base class.

2. **Wide context per probe point.** Each method carries every field that's useful for that moment — `task_id`, `role`, `round`, `cycle`, `spec_ref`, `verdict`, `duration_s`, whatever is available. Adapters pick what they render. Adding a field nobody currently uses costs one keyword arg at the call site and one parameter in the protocol method — zero breakage to existing adapters (Python keyword args with defaults).

3. **Probes are ports.** The orchestrator depends on `OrchestratorProbe`, a Protocol. Adapters implement it. Wiring structlog, Matrix, a future OTel exporter, or a SQLite trace store is an adapter swap, not a domain change.

4. **Must not raise.** Probe implementations must isolate their own errors. A Matrix POST failure must never propagate into the orchestrator loop.

## The Probe Interface

Lives in `ports/probe.py`. Pure Protocol — no implementation, no I/O.

```python
# ports/probe.py

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
        max_rounds: int,
        overlay: str | None,
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
        verdict: str,           # "pass" | "fail" | "error" | "timeout"
        round: int,
        cycle: int,
        spec_ref: str,
        findings_count: int,
        detail: str,
        duration_s: float,      # wall time from spawn to reap
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
        findings_preview: str,  # first 200 chars — enough for a Matrix message
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
        """Task reached terminal failure (max_rounds or pipeline failure)."""
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
        outcome: str,           # "merged" | "rebase_conflict" | "merge_conflict"
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
        attempt: int,           # which consecutive attempt this is
        max_attempts: int,
        looping_back: bool,     # True if this attempt exceeded max and task loops back
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
```

### Adding a new field

The probe interface uses keyword-only arguments. To add `commit_sha` to `worker_reaped`:

1. Add `commit_sha: str` to the method signature in `ports/probe.py`.
2. Add the argument at the call site in `loop.py`.
3. Adapters that don't use it yet ignore it or add it to their output — their existing code still compiles because Python keyword args with defaults don't break callers.

That is the full change. No dataclass. No union update. No dispatch rewrite.

### Naming conventions

Attribute names are the method parameter names. They are the schema. Conventions:

| Convention | Example |
|---|---|
| Snake case, no abbreviations | `task_id`, `spec_ref`, `findings_count` |
| Durations always `_s` suffix | `duration_s` |
| Counts always `_count` suffix | `findings_count` |
| IDs always `_id` / `_ids` suffix | `task_id`, `spawned_ids` |
| Booleans plain or `is_`/`has_` | `cleared`, `success`, `looping_back` |
| Outcome enumerations as `str` literals | `"pass"`, `"merged"`, `"rebase_conflict"` |
| Previews always `_preview` suffix | `findings_preview` |

These names appear verbatim in structlog output and Matrix messages. Consistency means grep works.

## Null and Multi Implementations

Both live in `adapters/probe.py` alongside each other.

```python
# adapters/probe.py

class NullProbe:
    """Discards all probe calls. Default when observability is not configured."""

    def orchestrator_started(self, **_: object) -> None: pass
    def orchestrator_halted(self, **_: object) -> None: pass
    def cycle_started(self, **_: object) -> None: pass
    def cycle_completed(self, **_: object) -> None: pass
    def worker_spawned(self, **_: object) -> None: pass
    def worker_reaped(self, **_: object) -> None: pass
    def task_advanced(self, **_: object) -> None: pass
    def task_looped_back(self, **_: object) -> None: pass
    def task_completed(self, **_: object) -> None: pass
    def task_failed(self, **_: object) -> None: pass
    def gate_checked(self, **_: object) -> None: pass
    def merge_attempted(self, **_: object) -> None: pass
    def rebase_conflict(self, **_: object) -> None: pass
    def intake_ran(self, **_: object) -> None: pass
    def process_improver_ran(self, **_: object) -> None: pass
    def recovery_started(self, **_: object) -> None: pass
    def orphan_found(self, **_: object) -> None: pass


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
                # Use structlog directly — the probe itself may be broken
                import structlog
                structlog.get_logger().exception(
                    "probe_error", probe=type(probe).__name__, method=method
                )

    def orchestrator_started(self, **kw: object) -> None:
        self._call("orchestrator_started", **kw)

    # ... same pattern for every method
```

`MultiProbe._call` uses `**kwargs` forwarding so it doesn't need updating when new keyword args are added to individual methods. The type checker enforces correctness at the call sites; `MultiProbe` is glue.

## Adapters

### StructlogProbe

Translates probe calls into structured log entries using [structlog](https://www.structlog.org/).

**Log level mapping:**

| Probe method | Level |
|---|---|
| `cycle_started` | `debug` |
| `gate_checked` (not cleared) | `debug` |
| `worker_spawned` | `debug` |
| `task_advanced` | `debug` |
| `cycle_completed` | `info` |
| `orchestrator_started` | `info` |
| `worker_reaped` (pass) | `info` |
| `task_completed` | `info` |
| `merge_attempted` (merged) | `info` |
| `intake_ran` | `info` |
| `process_improver_ran` | `info` |
| `gate_checked` (cleared) | `info` |
| `recovery_started` | `info` |
| `worker_reaped` (fail/error/timeout) | `warning` |
| `task_looped_back` | `warning` |
| `rebase_conflict` | `warning` |
| `merge_attempted` (conflict) | `warning` |
| `orphan_found` | `warning` |
| `task_failed` | `error` |
| `orchestrator_halted` (non-convergence) | `error` |

**Output format:**

Every probe call becomes one structlog log line. All keyword arguments become structlog bound keys — the method name becomes the event string.

Console mode (default, human-readable):
```
2026-04-15T14:23:01Z [info     ] worker_reaped    cycle=7 duration_s=142.3 findings_count=0 role=verifier round=0 spec_ref=specs/persistence.md task_id=task-003 verdict=pass
2026-04-15T14:23:01Z [warning  ] task_looped_back  cycle=7 findings_count=3 findings_preview="Tests failed: missing null check..." round=2 spec_ref=specs/widget.md task_id=task-001
```

JSON mode (for piping to log aggregators):
```json
{"timestamp": "2026-04-15T14:23:01Z", "level": "info", "event": "worker_reaped", "task_id": "task-003", "role": "verifier", "verdict": "pass", "round": 0, "cycle": 7, "spec_ref": "specs/persistence.md", "findings_count": 0, "duration_s": 142.3, "detail": "All tests pass"}
```

**Context binding:**

`StructlogProbe` uses structlog's `bind()` to carry ambient context without threading it through every call. When the orchestrator starts a cycle, the probe binds `cycle=N` to its internal logger. All subsequent log lines in that cycle carry it automatically — the call site doesn't pass `cycle` explicitly.

```python
class StructlogProbe:
    def __init__(self, log_format: str = "console", log_level: str = "info") -> None:
        self._log = structlog.get_logger()

    def cycle_started(self, *, cycle: int, **kw: object) -> None:
        # Bind cycle number — all subsequent calls carry it until next cycle
        self._log = self._log.bind(cycle=cycle)
        self._log.debug("cycle_started", **kw)

    def worker_reaped(self, *, task_id: str, verdict: str,
                      duration_s: float, **kw: object) -> None:
        level = "info" if verdict == "pass" else "warning"
        getattr(self._log, level)(
            "worker_reaped",
            task_id=task_id,
            verdict=verdict,
            duration_s=round(duration_s, 1),
            **kw,
        )
```

**This replaces all existing stdlib `logging` usage.** Every `logger = logging.getLogger(__name__)` in `loop.py`, `compose.py`, `serial.py`, `adapters/` is replaced with `structlog.get_logger()`. Operational messages that are not probe calls (e.g., "kustomize build failed: ...") use structlog directly — they are not probe calls but they get the same structured output.

### MatrixProbe

Posts probe calls as formatted Markdown messages to a Matrix room via the client-server API.

**Transport:** Single authenticated PUT request per message using `httpx`. The Matrix send-message endpoint (`PUT /_matrix/client/v3/rooms/{roomId}/send/m.room.message/{txnId}`) takes a JSON body with `msgtype` and `body` (plain text) plus `formatted_body` (HTML/Markdown). No SDK needed for v1.

**Signal filtering:**

Matrix is for humans watching in real time. Noise defeats the purpose.

Always sent (high signal):
- `worker_reaped` — verdict, duration, detail
- `task_looped_back` — round, findings preview
- `task_completed` — total rounds, total cycles
- `task_failed` — reason
- `merge_attempted` — outcome
- `rebase_conflict` (only when `looping_back=True`) — exceeded max attempts
- `orphan_found` — unexpected state
- `orchestrator_halted` — final result

Sent only when `verbose: true`:
- `worker_spawned`, `cycle_completed`, `intake_ran`, `process_improver_ran`, `orchestrator_started`, `recovery_started`

Never sent (too noisy even in verbose):
- `cycle_started`, `gate_checked` (not cleared), `task_advanced`

Gate cleared (`gate_checked` with `cleared=True`) is sent always — it's a human action being acknowledged.

**Message format:**

```
✅ task-003 · verifier passed (round 0, 142s)
All tests pass, check scripts pass
```
```
🔁 task-001 · looped back to implementer (round 2)
> Tests failed: missing null check in widget.py line 42...
```
```
❌ task-001 · FAILED after 50 rounds
Pipeline failure: no enclosing loop at step [0, 1]
```
```
🎉 task-003 · complete (1 round, 3 cycles)
```

**Task threading:**

The first message for each `task_id` in a run is sent as a new message. Subsequent messages for the same task are sent as thread replies (Matrix `m.thread` relation), grouping all events for a task into a single thread. The probe tracks `task_id -> event_id` in memory.

**Error isolation:**

`httpx` calls are wrapped in try/except. Any failure (network, auth, rate limit) is logged via structlog and swallowed. The Matrix room going down must not stall the orchestrator.

**Access token:**

Read from an environment variable named by `token_env` config key. Never stored in `.hyperloop.yaml`.

### RecordingProbe (test fake)

```python
# tests/fakes/probe.py

from dataclasses import dataclass, field
from typing import Any

@dataclass
class RecordedCall:
    method: str
    kwargs: dict[str, Any]

class RecordingProbe:
    """Captures all probe calls for test assertions. No output."""

    def __init__(self) -> None:
        self.calls: list[RecordedCall] = []

    def _record(self, method: str, **kwargs: object) -> None:
        self.calls.append(RecordedCall(method=method, kwargs=dict(kwargs)))

    def of_method(self, method: str) -> list[dict[str, Any]]:
        """Return kwargs of all calls to the named method."""
        return [c.kwargs for c in self.calls if c.method == method]

    def last(self, method: str) -> dict[str, Any]:
        """Return kwargs of the most recent call to the named method."""
        calls = self.of_method(method)
        if not calls:
            raise AssertionError(f"No calls to {method!r}")
        return calls[-1]

    def orchestrator_started(self, **kw: object) -> None: self._record("orchestrator_started", **kw)
    def orchestrator_halted(self, **kw: object) -> None: self._record("orchestrator_halted", **kw)
    def cycle_started(self, **kw: object) -> None: self._record("cycle_started", **kw)
    def cycle_completed(self, **kw: object) -> None: self._record("cycle_completed", **kw)
    def worker_spawned(self, **kw: object) -> None: self._record("worker_spawned", **kw)
    def worker_reaped(self, **kw: object) -> None: self._record("worker_reaped", **kw)
    def task_advanced(self, **kw: object) -> None: self._record("task_advanced", **kw)
    def task_looped_back(self, **kw: object) -> None: self._record("task_looped_back", **kw)
    def task_completed(self, **kw: object) -> None: self._record("task_completed", **kw)
    def task_failed(self, **kw: object) -> None: self._record("task_failed", **kw)
    def gate_checked(self, **kw: object) -> None: self._record("gate_checked", **kw)
    def merge_attempted(self, **kw: object) -> None: self._record("merge_attempted", **kw)
    def rebase_conflict(self, **kw: object) -> None: self._record("rebase_conflict", **kw)
    def intake_ran(self, **kw: object) -> None: self._record("intake_ran", **kw)
    def process_improver_ran(self, **kw: object) -> None: self._record("process_improver_ran", **kw)
    def recovery_started(self, **kw: object) -> None: self._record("recovery_started", **kw)
    def orphan_found(self, **kw: object) -> None: self._record("orphan_found", **kw)
```

### Future adapters

The probe protocol supports these without any domain or port changes:

- **OpenTelemetry:** `worker_spawned` starts a span, `worker_reaped` ends it with attributes. Each cycle is a parent span. Exports to Jaeger/Tempo/Grafana.
- **SQLite trace store:** each call appends a row. Query with SQL for post-mortems: `SELECT task_id, SUM(duration_s) FROM worker_reaped GROUP BY task_id`.
- **Webhook:** serialize kwargs to JSON, POST to a URL.

## Timing

The `StructlogProbe` and `MatrixProbe` track spawn times to compute `duration_s`. They maintain an internal dict:

```python
self._spawn_times: dict[str, float] = {}  # task_id -> time.monotonic()

def worker_spawned(self, *, task_id: str, **kw: object) -> None:
    self._spawn_times[task_id] = time.monotonic()
    ...

def worker_reaped(self, *, task_id: str, duration_s: float, **kw: object) -> None:
    ...
```

`duration_s` is computed by the orchestrator loop at the reap site — the loop already knows when the worker was spawned (it tracks `_workers: dict[str, tuple[WorkerHandle, PipelinePosition]]`). It passes `duration_s` to the probe. The probe doesn't need to track spawn times independently.

For cycle duration: the loop records `time.monotonic()` at the start of `run_cycle` and passes `duration_s` to `cycle_completed`.

For serial agent duration: `_run_intake` and `_run_process_improver` time their own subprocess calls and pass `duration_s` to the probe.

## Wiring

### Orchestrator

`Orchestrator.__init__` accepts a `probe` parameter, replacing `on_cycle`:

```python
def __init__(
    self,
    state: StateStore,
    runtime: Runtime,
    process: Process,
    max_workers: int = 6,
    max_rounds: int = 50,
    pr_manager: PRPort | None = None,
    composer: PromptComposer | None = None,
    repo_path: str | None = None,
    poll_interval: float = 30.0,
    probe: OrchestratorProbe | None = None,    # replaces on_cycle
    serial_runner: SerialRunner | None = None,
    max_action_attempts: int = 3,
) -> None:
    ...
    self._probe = probe or NullProbe()
```

Call sites in `run_cycle`:

```python
# Start of cycle
cycle_start = time.monotonic()
self._probe.cycle_started(
    cycle=cycle_num,
    active_workers=len(self._workers),
    not_started=..., in_progress=..., complete=..., failed=...,
)

# After reaping a worker
self._probe.worker_reaped(
    task_id=task_id,
    role=handle.role,
    verdict=result.verdict.value,
    round=task.round,
    cycle=cycle_num,
    spec_ref=task.spec_ref,
    findings_count=result.findings,
    detail=result.detail,
    duration_s=time.monotonic() - spawn_time,
)

# After spawning a worker
self._probe.worker_spawned(
    task_id=task_id,
    role=role,
    branch=branch,
    round=task.round,
    cycle=cycle_num,
    spec_ref=task.spec_ref,
)

# End of cycle
self._probe.cycle_completed(
    cycle=cycle_num,
    active_workers=len(self._workers),
    not_started=..., in_progress=..., complete=..., failed=...,
    spawned_ids=tuple(spawned_task_ids),
    reaped_ids=tuple(reaped_task_ids),
    duration_s=time.monotonic() - cycle_start,
)
```

The orchestrator also needs to track spawn times for workers. The `_workers` dict currently maps `task_id -> (WorkerHandle, PipelinePosition)`. Extend to `task_id -> (WorkerHandle, PipelinePosition, float)` where the float is `time.monotonic()` at spawn.

### Configuration

`.hyperloop.yaml` gains an `observability` section:

```yaml
observability:
  log_format: console       # console | json
  log_level: info           # debug | info | warning | error

  matrix:                   # optional — omit to disable
    homeserver: https://matrix.example.com
    room_id: "!abc123:example.com"
    token_env: MATRIX_ACCESS_TOKEN
    verbose: false
```

`Config` gains a corresponding `ObservabilityConfig` dataclass:

```python
@dataclass(frozen=True)
class MatrixConfig:
    homeserver: str
    room_id: str
    token_env: str
    verbose: bool

@dataclass(frozen=True)
class ObservabilityConfig:
    log_format: str          # "console" | "json"
    log_level: str           # "debug" | "info" | "warning" | "error"
    matrix: MatrixConfig | None
```

### CLI construction

```python
def _build_probe(cfg: ObservabilityConfig) -> OrchestratorProbe:
    probes: list[OrchestratorProbe] = []

    # Always: structlog
    configure_logging(log_format=cfg.log_format, log_level=cfg.log_level)
    probes.append(StructlogProbe())

    # Optional: Matrix
    if cfg.matrix is not None:
        token = os.environ.get(cfg.matrix.token_env)
        if token:
            probes.append(MatrixProbe(
                homeserver=cfg.matrix.homeserver,
                room_id=cfg.matrix.room_id,
                access_token=token,
                verbose=cfg.matrix.verbose,
            ))
        else:
            log.warning("matrix_token_missing", env_var=cfg.matrix.token_env)

    return MultiProbe(tuple(probes)) if len(probes) > 1 else probes[0]
```

## structlog Setup

Configured once at startup, before any logging occurs. Modules that need operational logging (not probe calls) use `structlog.get_logger()` directly.

```python
# src/hyperloop/logging.py

import logging
import structlog


def configure_logging(log_format: str = "console", log_level: str = "info") -> None:
    """Configure structlog for the process. Call once at startup."""

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
    ]

    if log_format == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

All modules replace `logging.getLogger(__name__)` with:

```python
import structlog
log = structlog.get_logger()
```

## Testing

### What to test

**Probe protocol** (`tests/test_probe.py`):
- `NullProbe` accepts all calls without raising.
- `MultiProbe` fans out to all children.
- `MultiProbe` catches exceptions from one child, logs them, and still calls remaining children.
- `RecordingProbe.of_method` and `.last` return correct data.

**StructlogProbe** (`tests/test_structlog_probe.py`):
- Each probe method produces a structlog entry with the correct event name and level.
- `worker_reaped` with `verdict="fail"` logs at `warning`.
- `worker_reaped` with `verdict="pass"` logs at `info`.
- `duration_s` appears in the log output.
- Uses `structlog.testing.capture_logs()` — no subprocess, no I/O.

**MatrixProbe** (`tests/test_matrix_probe.py`):
- High-signal probe calls produce an HTTP PUT request to the correct Matrix endpoint.
- Low-signal calls (e.g., `cycle_started`) produce no HTTP request.
- Task threading: second call for same `task_id` sends a thread reply.
- HTTP failure is swallowed, not raised.
- Uses `httpx.MockTransport` or a `respx` fixture — no real Matrix server.

**Loop integration** (`tests/test_loop.py`):
- Existing tests gain a `RecordingProbe` parameter via `_make_orchestrator`.
- A full pass cycle emits `worker_spawned`, `worker_reaped` (pass), `task_completed` with correct kwargs.
- A fail-then-pass cycle emits `task_looped_back` with `findings_preview` populated.
- `cycle_completed` carries correct `spawned_ids` and `reaped_ids`.
- `orchestrator_halted` fires when `run_loop` returns.

### No mocks

`RecordingProbe` is a real implementation of `OrchestratorProbe`. `httpx.MockTransport` is a real transport adapter, not a mock — it implements the transport protocol without calling the network.

## File Map

```
src/hyperloop/
├── domain/
│   ├── model.py
│   ├── decide.py
│   ├── pipeline.py
│   └── deps.py
├── ports/
│   ├── probe.py               ← OrchestratorProbe protocol (NEW)
│   ├── state.py
│   ├── runtime.py
│   ├── pr.py
│   └── serial.py
├── adapters/
│   ├── probe.py               ← NullProbe, MultiProbe (NEW)
│   ├── structlog_probe.py     ← StructlogProbe (NEW)
│   ├── matrix_probe.py        ← MatrixProbe (NEW)
│   ├── git_state.py
│   ├── local.py
│   └── serial.py
├── logging.py                 ← configure_logging() (NEW)
├── compose.py
├── config.py                  ← gains ObservabilityConfig, MatrixConfig
├── loop.py                    ← gains probe: OrchestratorProbe param, probe call sites
└── cli.py                     ← gains _build_probe(), drops on_cycle
tests/
├── fakes/
│   ├── probe.py               ← RecordingProbe (NEW)
│   ├── state.py
│   ├── runtime.py
│   └── pr.py
├── test_probe.py              ← NullProbe, MultiProbe, RecordingProbe (NEW)
├── test_structlog_probe.py    ← StructlogProbe with capture_logs() (NEW)
├── test_matrix_probe.py       ← MatrixProbe with MockTransport (NEW)
├── test_loop.py               ← updated: RecordingProbe instead of on_cycle
└── ...
```

The dependency rule is preserved: `ports/probe.py` has no imports from `adapters/`. `domain/` has no imports from `ports/` or `adapters/`. Adapters import from `ports/` and `domain/` only.

## Dependencies

Add to `pyproject.toml`:

```toml
dependencies = [
    "pyyaml>=6.0.3",
    "rich>=15.0.0",
    "typer>=0.24.1",
    "structlog>=24.0",
    "httpx>=0.27",
]
```
