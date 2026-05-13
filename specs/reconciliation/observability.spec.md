# Observability Specification

## Purpose

The reconciliation engine observes significant moments through domain probes — typed protocol methods called at each observation point. Adapters translate probe calls into structured logs, chat messages, telemetry spans, or file records. Probe failures never propagate into the reconciler loop. All observation code MUST use probe method calls; direct logger calls are prohibited.

## Requirements

### Requirement: Domain Probe Pattern

The Observer SHALL be a typed protocol with one method per observation point. Each method has keyword-only arguments defining the exact schema for that event. This provides compile-time type safety and self-documenting schemas.

#### Scenario: Probe call at observation point

- GIVEN the reconciler dispatches a task
- WHEN it calls the task_dispatched probe with typed arguments (task_id, spec_path, spec_blob_sha, etc.)
- THEN all registered probe adapters receive the call with the same typed arguments

#### Scenario: Type safety at call sites

- GIVEN a probe method `task_failed(*, task_id: int, spec_path: str, reason: str)`
- WHEN a call site passes an incorrect argument name
- THEN the type checker reports an error at compile time

### Requirement: No Direct Logging

Domain and reconciler code MUST NOT call logger, structlog, or any logging library directly. All observation SHALL flow through probe method calls. Structured log adapters translate probe calls to log entries.

#### Scenario: Observation through probes only

- GIVEN the reconciler detects a verification failure
- WHEN it needs to record this observation
- THEN it calls the verification_failed probe method
- AND no `logger.error()` or equivalent exists in the reconciler code

### Requirement: Error Isolation

Probe adapters MUST NOT raise exceptions into the reconciler. All adapter errors SHALL be caught and suppressed.

#### Scenario: Adapter failure does not disrupt reconciler

- GIVEN a chat notification adapter fails to connect
- WHEN a probe method is called
- THEN the error is caught
- AND other adapters still receive the call
- AND the reconciliation loop continues uninterrupted

### Requirement: Multi-Probe Fan-Out

Multiple probe adapters SHALL receive every probe call. The system SHALL support composing N adapters into a single probe instance that fans out all calls.

#### Scenario: Three adapters receive same event

- GIVEN adapters for structured logging, chat, and telemetry are registered
- WHEN a probe method is called
- THEN all three adapters receive the call independently
- AND failures in one adapter do not affect the others

### Requirement: NullProbe

A NullProbe adapter SHALL exist that discards all probe calls. It is the default when no observability is configured.

#### Scenario: NullProbe as default

- GIVEN no observability adapters are configured
- WHEN the reconciler starts
- THEN it uses the NullProbe
- AND all probe calls are silently discarded

### Requirement: Probe Method Catalog

The probe protocol SHALL define methods for the following observation points. Each method uses keyword-only arguments with the types and semantics shown.

**Reconciler Lifecycle:**

| Method | When | Key Arguments |
|---|---|---|
| reconciler_started | Reconciler begins (including after recovery) | spec_count: int, cycle: int |
| reconciler_halted | Reconciler loop exits | reason: str, total_cycles: int |

**Cycle:**

| Method | When | Key Arguments |
|---|---|---|
| cycle_started | Reconciliation cycle begins | cycle: int, specs_out_of_sync: int, tasks_in_progress: int |
| cycle_completed | Cycle ends | cycle: int, duration_s: float, specs_out_of_sync: int, tasks_dispatched: int, tasks_completed: int, tasks_failed: int |

**Divergence Detection:**

| Method | When | Key Arguments |
|---|---|---|
| spec_divergence_detected | New, modified, or deleted spec found | spec_path: str, blob_sha: str, change_type: ChangeType (new, modified, deleted) |
| spec_superseded | SpecPlan marked superseded by new SHA | spec_path: str, old_sha: str, new_sha: str |

**Decomposition:**

| Method | When | Key Arguments |
|---|---|---|
| decomposition_started | Decomposition agent invoked | specs_count: int, cycle: int |
| decomposition_completed | Decomposition agent returned tasks | specs_count: int, tasks_created: int, cycle: int, duration_s: float |
| decomposition_failed | Decomposition agent failed | reason: str, cycle: int |

**Task Lifecycle:**

| Method | When | Key Arguments |
|---|---|---|
| task_created | New task added to Plan | task_id: int, spec_path: str, spec_blob_sha: str, name: str, depends_on: list[int] |
| task_dispatched | Task sent to inner loop | task_id: int, spec_path: str, spec_blob_sha: str, retry_count: int, cycle: int |
| task_completed | Task finished successfully | task_id: int, spec_path: str, spec_blob_sha: str, cycle: int |
| task_failed | Task failed | task_id: int, spec_path: str, spec_blob_sha: str, reason: str, retry_count: int, cycle: int |
| task_retried | Task being retried after failure | task_id: int, spec_path: str, reason: str, retry_count: int, cycle: int |
| dependency_invalidated | Task failed due to unsatisfiable dependency | task_id: int, spec_path: str, dependency_task_id: int, reason: str |

**Merge:**

| Method | When | Key Arguments |
|---|---|---|
| task_merge_completed | Task work merged into delivery workspace | task_id: int, spec_blob_sha: str |
| task_merge_conflict | Merge conflict detected | task_id: int, spec_blob_sha: str |
| merge_resolution_launched | Merge resolution agent started | task_id: int, spec_blob_sha: str |
| merge_resolution_completed | Merge resolution finished | task_id: int, spec_blob_sha: str, success: bool |
| trunk_integration_started | PR opened for spec delivery | spec_path: str, spec_blob_sha: str, integration_id: str |
| trunk_integration_completed | PR merged to trunk | spec_path: str, spec_blob_sha: str, integration_id: str |
| trunk_integration_failed | PR merge to trunk failed | spec_path: str, spec_blob_sha: str, reason: str |

**Verification:**

| Method | When | Key Arguments |
|---|---|---|
| verification_launched | Verification agent started | spec_path: str, spec_blob_sha: str, cycle: int |
| verification_passed | Verification confirmed alignment | spec_path: str, spec_blob_sha: str, rationale: str, cycle: int |
| verification_failed | Verification found misalignment | spec_path: str, spec_blob_sha: str, rationale: str, cycle: int |

**State Transitions:**

| Method | When | Key Arguments |
|---|---|---|
| spec_synced | Spec reached Synced state | spec_path: str, spec_blob_sha: str, total_tasks: int, cycle: int |
| spec_failed | Spec reached Failed state | spec_path: str, spec_blob_sha: str, reason: str, cycle: int |
| redecomposition_triggered | Spec sent back to decomposition after task exhaustion | spec_path: str, spec_blob_sha: str, failed_task_count: int, cycle: int |

**Agent Lifecycle:**

| Method | When | Key Arguments |
|---|---|---|
| agent_cancelled | Agent cancelled (superseding, deletion) | task_id: int, spec_path: str, reason: str |
| stale_agent_detected | Stale agent found after crash | task_id: int, spec_path: str |
| agent_launch_failed | Agent runtime failed to launch | task_id: int, role: str, reason: str, cycle: int |

**Recovery:**

| Method | When | Key Arguments |
|---|---|---|
| crash_recovery_started | Reconciler recovering from crash | stale_agent_count: int |

**Prompt Composition:**

| Method | When | Key Arguments |
|---|---|---|
| composer_rebuilt | Prompt templates rebuilt from overlays | template_count: int |
| composer_rebuild_failed | Kustomize build failed during rebuild | reason: str |

**Plan Persistence:**

| Method | When | Key Arguments |
|---|---|---|
| plan_synced | Plan persisted and synced | cycle: int |

#### Scenario: Every state transition emits a probe

- GIVEN a spec transitions from Reconciling to Verifying
- WHEN the transition occurs
- THEN the verification_launched probe is called with the spec details

#### Scenario: Probe arguments match Plan data model

- GIVEN a task_created probe is called
- WHEN the arguments are examined
- THEN task_id, spec_path, and spec_blob_sha match the Task fields defined in plan.spec.md
