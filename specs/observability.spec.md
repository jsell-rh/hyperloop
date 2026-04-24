# Observability Specification

## Purpose

The system emits structured events at significant moments during reconciliation and task processing. Observability is implemented through the Observer port with a single emit method. Adapters translate events into logs, chat messages, telemetry spans, or file records. Observer failures never propagate into the orchestrator loop.

## Requirements

### Requirement: Single Emit Method

The Observer port SHALL expose a single method: emit(event_name, **kwargs). All observation flows through this one method.

#### Scenario: Event emission

- GIVEN the task processor spawns a worker
- WHEN it calls emit("worker_spawned", task_id="t-001", role="implementer", ...)
- THEN all registered observer adapters receive the event name and kwargs

#### Scenario: Adding a new event

- GIVEN a new observation point is needed (e.g., "audit_completed")
- WHEN the developer adds an emit() call at the site
- THEN no interface changes are needed
- AND no adapter code changes are required (adapters filter by event name)

### Requirement: Error Isolation

Observer adapters MUST NOT raise exceptions into the orchestrator. All adapter errors SHALL be logged and swallowed.

#### Scenario: Adapter failure

- GIVEN a chat notification adapter fails to connect
- WHEN an event is emitted
- THEN the error is logged
- AND other adapters still receive the event
- AND the orchestrator loop continues uninterrupted

### Requirement: Multi-Observer Fan-Out

Multiple observer adapters SHALL receive every event. The system SHALL support composing N adapters into a single observer that fans out all events.

#### Scenario: Three adapters

- GIVEN adapters for structured logging, chat, and telemetry are registered
- WHEN an event is emitted
- THEN all three adapters receive the event independently
- AND failures in one adapter do not affect the others

### Requirement: Event Catalog

The system SHALL emit events at these moments:

**Orchestrator Lifecycle:**

| Event | When | Key Data |
|---|---|---|
| orchestrator_started | Orchestrator begins after recovery | task_count, max_workers |
| orchestrator_halted | Orchestrator loop exits | reason, total_cycles, completed_tasks, failed_tasks |

**Cycle:**

| Event | When | Key Data |
|---|---|---|
| cycle_started | Reconciler + task processor cycle begins | cycle, task status counts |
| cycle_completed | Cycle ends | cycle, spawned_ids, reaped_ids, duration_s |

**Workers:**

| Event | When | Key Data |
|---|---|---|
| worker_spawned | Worker agent started | task_id, role, branch, round, cycle |
| worker_reaped | Worker agent completed | task_id, role, verdict, round, detail, duration_s |
| worker_message | Worker produces output | task_id, role, message_type, content |
| spawn_failed | Worker spawn failed | task_id, role, attempt, max_attempts, cycle |

**Tasks:**

| Event | When | Key Data |
|---|---|---|
| task_advanced | Task moved to new phase | task_id, from_phase, to_phase, round, cycle |
| task_completed | Task reached "synced" | task_id, spec_ref, total_rounds, cycle |
| task_failed | Task reached "failed" | task_id, spec_ref, reason, round, cycle |
| task_retried | Task looped back to earlier phase | task_id, spec_ref, round, cycle, findings_preview |
| task_reset | Task reset to not-started | task_id, spec_ref, reason, cycle |

**Reconciler:**

| Event | When | Key Data |
|---|---|---|
| drift_detected | Spec drift found (coverage, freshness, alignment) | spec_path, drift_type, detail |
| intake_ran | PM intake completed | created_tasks, success, cycle, duration_s |
| audit_ran | Alignment audit completed | spec_ref, result, cycle, duration_s |
| process_improver_ran | Process-improver completed | failed_task_ids, success, cycle, duration_s |
| gc_ran | Garbage collection completed | pruned_count, cycle |

**Signals and Actions:**

| Event | When | Key Data |
|---|---|---|
| signal_checked | Signal polled at gate | task_id, signal_name, status, cycle |
| step_executed | Mechanical step executed | task_id, step_name, outcome, cycle |

**Recovery:**

| Event | When | Key Data |
|---|---|---|
| recovery_started | Orchestrator recovering from crash | in_progress_tasks |
| orphan_found | Orphaned worker detected | task_id, branch |

**State:**

| Event | When | Key Data |
|---|---|---|
| state_synced | State branch synced with remote | cycle |
| overlay_reloaded | Prompt overlays hot-reloaded | cycle |

### Requirement: Structured Log Adapter

A structured log adapter SHALL translate events into structured log entries with appropriate log levels.

#### Scenario: Log level mapping

- GIVEN an event "task_failed"
- WHEN the structured log adapter receives it
- THEN it logs at ERROR level
- AND events like "task_completed" log at INFO
- AND events like "cycle_started" log at DEBUG

### Requirement: Chat Notification Adapter

A chat notification adapter SHALL post formatted messages to a chat room, filtering events by signal importance.

#### Scenario: High-signal events posted

- GIVEN events "worker_reaped", "task_completed", "task_failed"
- WHEN the chat adapter receives them
- THEN they are posted as formatted messages
- AND low-signal events like "cycle_started" are suppressed

#### Scenario: Task threading

- GIVEN multiple events for task-001
- WHEN the chat adapter posts them
- THEN subsequent messages for the same task are threaded under the first

### Requirement: Telemetry Adapter

A telemetry adapter SHALL export events as spans and metrics via a standard telemetry protocol.

#### Scenario: Span creation

- GIVEN events "worker_spawned" and "worker_reaped" for the same task
- WHEN the telemetry adapter processes them
- THEN it creates a span covering the worker's lifetime
- AND attaches task_id, role, verdict as span attributes

### Requirement: File Adapter

A file adapter SHALL write events as newline-delimited JSON for consumption by the dashboard.

#### Scenario: Event written to file

- GIVEN the file adapter is configured
- WHEN an event is emitted
- THEN a JSON line is appended to the events file
- AND the file is capped at a configured maximum number of events
