# Observability Specification

## Purpose

The system observes significant moments during reconciliation and task processing through domain probes — typed protocol methods called at each observation point. Adapters translate probe calls into logs, chat messages, telemetry spans, or file records. Probe failures never propagate into the orchestrator loop. Code MUST use probe method calls for all observation; direct logger calls are banned.

## Requirements

### Requirement: Domain Probe Pattern

The Observer SHALL be a typed protocol with one method per observation point. Each method has keyword-only arguments defining the exact schema for that event. This provides compile-time safety and self-documenting schemas.

#### Scenario: Probe call at observation point

- GIVEN the task processor spawns a worker
- WHEN it calls `self._probe.worker_spawned(task_id="t-001", role="implementer", branch="task-001", round=0, cycle=3, spec_ref="specs/auth.md@abc123")`
- THEN all registered probe adapters receive the call with typed arguments

#### Scenario: Adding a new probe point

- GIVEN a new observation point is needed (e.g., audit_completed)
- WHEN the developer adds it
- THEN they add a method to the probe protocol with typed keyword arguments
- AND implement the method in each adapter (NullProbe, MultiProbe, and active adapters)
- AND the type checker verifies all call sites pass correct arguments

#### Scenario: Type safety at call sites

- GIVEN a probe method `worker_reaped(*, task_id: str, role: str, verdict: str, duration_s: float)`
- WHEN a call site passes `duration_sec=1.5` (typo)
- THEN the type checker reports an error at compile time
- AND the typo cannot reach production

### Requirement: No Direct Logging

Domain and orchestrator code MUST NOT call logger.*, structlog.*, or any logging library directly. All observation SHALL flow through probe method calls. Structured log adapters translate probe calls to log entries.

#### Scenario: Logging through probes only

- GIVEN the orchestrator detects a task failure
- WHEN it needs to record this observation
- THEN it calls `self._probe.task_failed(task_id=..., reason=..., ...)`
- AND the structured log adapter translates this to a log entry at ERROR level
- AND no `logger.error()` call exists in the orchestrator code

### Requirement: Error Isolation

Probe adapters MUST NOT raise exceptions into the orchestrator. All adapter errors SHALL be caught and swallowed (logged to stderr as a last resort).

#### Scenario: Adapter failure

- GIVEN a chat notification adapter fails to connect
- WHEN a probe method is called
- THEN the error is caught
- AND other adapters still receive the call
- AND the orchestrator loop continues uninterrupted

### Requirement: Multi-Probe Fan-Out

Multiple probe adapters SHALL receive every probe call. The system SHALL support composing N adapters into a single probe that fans out all calls.

#### Scenario: Three adapters

- GIVEN adapters for structured logging, chat, and telemetry are registered
- WHEN a probe method is called
- THEN all three adapters receive the call independently
- AND failures in one adapter do not affect the others

### Requirement: NullProbe

A NullProbe adapter SHALL discard all probe calls. It is the default when no observability is configured. NullProbe accepts all method signatures with `**_: object` and does nothing.

### Requirement: Probe Method Catalog

The probe protocol SHALL define methods for these observation points:

**Orchestrator Lifecycle:**

| Method | When | Key Arguments |
|---|---|---|
| orchestrator_started | Orchestrator begins after recovery | task_count, max_workers, max_task_rounds |
| orchestrator_halted | Orchestrator loop exits | reason, total_cycles, completed_tasks, failed_tasks |

**Cycle:**

| Method | When | Key Arguments |
|---|---|---|
| cycle_started | Reconciler + task processor cycle begins | cycle, active_workers, not_started, in_progress, completed, failed |
| cycle_completed | Cycle ends | cycle, active_workers, not_started, in_progress, completed, failed, spawned_ids, reaped_ids, duration_s |

**Workers:**

| Method | When | Key Arguments |
|---|---|---|
| worker_spawned | Worker agent started | task_id, role, branch, round, cycle, spec_ref |
| worker_reaped | Worker agent completed | task_id, role, verdict, round, cycle, spec_ref, detail, duration_s |
| worker_message | Worker produces output | task_id, role, message_type, content |
| spawn_failed | Worker spawn failed | task_id, role, branch, attempt, max_attempts, cooldown_cycles, cycle |

**Tasks:**

| Method | When | Key Arguments |
|---|---|---|
| task_advanced | Task moved to new phase | task_id, spec_ref, from_phase, to_phase, from_status, to_status, round, cycle |
| task_completed | Task reached terminal success | task_id, spec_ref, total_rounds, total_cycles, cycle |
| task_failed | Task reached terminal failure | task_id, spec_ref, reason, round, cycle |
| task_retried | Task looped back to earlier phase | task_id, spec_ref, round, cycle, findings_preview |
| task_reset | Task reset to not-started | task_id, spec_ref, reason, cycle |

**Reconciler:**

| Method | When | Key Arguments |
|---|---|---|
| drift_detected | Spec drift found | spec_path, drift_type (coverage, freshness, alignment), detail |
| intake_ran | PM intake completed | unprocessed_specs, created_tasks, success, cycle, duration_s |
| audit_ran | Alignment audit completed | spec_ref, result (aligned, misaligned), cycle, duration_s |
| process_improver_ran | Process-improver completed | failed_task_ids, success, cycle, duration_s |
| gc_ran | Garbage collection completed | pruned_count, cycle |
| convergence_marked | Spec marked as converged | spec_path, spec_ref, cycle |

**Signals and Actions:**

| Method | When | Key Arguments |
|---|---|---|
| signal_checked | Signal polled at gate | task_id, signal_name, status, message, cycle |
| step_executed | Mechanical step executed | task_id, step_name, outcome, detail, cycle |

**Forge:**

| Method | When | Key Arguments |
|---|---|---|
| pr_created | Draft PR created | task_id, pr_url, branch |
| pr_marked_ready | PR transitioned from draft to ready | pr_url |
| merge_attempted | PR merge attempted | task_id, branch, spec_ref, outcome, attempt, cycle |

**Recovery:**

| Method | When | Key Arguments |
|---|---|---|
| recovery_started | Orchestrator recovering from crash | in_progress_tasks |
| orphan_found | Orphaned worker detected and cancelled | task_id, branch |
| worker_crash_detected | Worker completed without verdict | task_id, role, branch |

**State:**

| Method | When | Key Arguments |
|---|---|---|
| state_synced | State branch synced with remote | cycle |
| overlay_reloaded | Prompt overlays hot-reloaded | cycle |

### Requirement: Structured Log Adapter

A structured log adapter SHALL translate probe method calls into structured log entries with appropriate log levels.

#### Scenario: Log level mapping

- GIVEN a probe call to task_failed()
- WHEN the structured log adapter receives it
- THEN it logs at ERROR level
- AND task_completed() logs at INFO
- AND cycle_started() logs at DEBUG
- AND worker_crash_detected() logs at WARNING

### Requirement: Chat Notification Adapter

A chat notification adapter SHALL post formatted messages to a chat room. Events are classified as high-signal (always posted) or verbose-only (posted when verbose mode is enabled).

#### Scenario: High-signal events posted

- GIVEN probe calls for worker_reaped, task_completed, task_failed, merge_attempted, worker_crash_detected
- WHEN the chat adapter receives them
- THEN they are posted as formatted messages
- AND low-signal events like cycle_started are suppressed unless verbose mode is enabled

#### Scenario: Signal classification is configurable

- GIVEN the chat adapter's signal classification
- WHEN a team needs different filtering
- THEN the classification SHOULD be configurable per-deployment
- AND the default classification covers common use cases

#### Scenario: Task threading

- GIVEN multiple probe calls for task-001
- WHEN the chat adapter posts them
- THEN subsequent messages for the same task are threaded under the first

### Requirement: Telemetry Adapter

A telemetry adapter SHALL export probe calls as spans and metrics via a standard telemetry protocol (e.g., OpenTelemetry).

#### Scenario: Span creation

- GIVEN probe calls worker_spawned() and worker_reaped() for the same task
- WHEN the telemetry adapter processes them
- THEN it creates a span covering the worker's lifetime
- AND attaches task_id, role, verdict as span attributes
- AND sets span status to ERROR if verdict is not "pass"

### Requirement: File Adapter

A file adapter SHALL write probe calls as newline-delimited JSON for consumption by the dashboard. The file adapter is local to the machine running the orchestrator.

#### Scenario: Event written to file

- GIVEN the file adapter is configured
- WHEN a probe method is called
- THEN a JSON line is appended to the events file with: timestamp, method name, and all kwargs

#### Scenario: Startup truncation

- GIVEN the events file exceeds the configured maximum events
- WHEN the file adapter starts
- THEN it truncates to the maximum, keeping the newest events
- AND during the run, events are appended without runtime capping
