# Task Lifecycle Specification

## Purpose

Defines how specs are decomposed into tasks, how tasks are scheduled for execution, and how task failures are handled. The task lifecycle governs the progression from "this spec needs work" to "this work is complete" or "human intervention is required."

## Requirements

### Requirement: Serial Decomposition

The decomposition agent SHALL process all OutOfSync specs serially (one at a time) to enable identification of cross-spec dependencies. The processing order is unspecified but MUST be deterministic within a single cycle.

#### Scenario: Cross-spec dependencies detected

- GIVEN specs A and B are both OutOfSync
- WHEN the decomposition agent processes them
- THEN it processes one fully before starting the next
- AND tasks from the second spec MAY declare dependencies on tasks from the first

#### Scenario: Decomposition produces zero tasks

- GIVEN a spec was modified with only cosmetic changes (whitespace, list reordering)
- WHEN the decomposition agent processes it
- THEN it MAY determine no implementation tasks are needed
- AND the spec transitions to Reconciling with zero tasks
- AND the "all tasks complete" condition is vacuously true, triggering transition to Verifying

### Requirement: Diff-Based Decomposition

The decomposition agent SHALL receive the diff between the last Synced blob SHA (if any) and the current blob SHA. This enables short-circuiting on cosmetic changes and scoping work to only what changed.

#### Scenario: Incremental change

- GIVEN a spec was previously Synced at SHA abc123
- WHEN the spec is modified to SHA def456
- THEN the decomposition agent receives the textual diff between abc123 and def456
- AND it creates tasks only for the changed behavior, not a full reimplementation

#### Scenario: New spec with no prior Synced state

- GIVEN a brand-new spec with no prior Synced SHA
- WHEN the decomposition agent processes it
- THEN it receives the full spec content (diff against empty)
- AND it creates tasks for the complete implementation

### Requirement: Failure-Aware Decomposition

When a spec returns to OutOfSync after a verification failure or task failure escalation, the decomposition agent SHALL receive all prior events (including VerificationFailed rationale and TaskFailed details) and produce only targeted corrective tasks.

#### Scenario: Targeted corrective tasks after verification failure

- GIVEN a spec failed verification with rationale "error handling does not cover network timeouts"
- WHEN the decomposition agent processes the spec
- THEN it receives the VerificationFailed event with the full rationale
- AND it produces tasks that specifically address the gap
- AND it does NOT recreate tasks for work that was already verified as correct

#### Scenario: Corrective tasks after task failure escalation

- GIVEN a spec was re-decomposed because task retries were exhausted
- WHEN the decomposition agent processes the spec
- THEN it receives all TaskFailed events with failure details
- AND it MAY restructure the work differently than the original decomposition

### Requirement: Task Dependencies

Tasks SHALL declare dependencies on other tasks by ID. Dependencies form a directed acyclic graph (DAG). The system MUST reject dependency sets that would create cycles.

#### Scenario: Valid dependency chain

- GIVEN task 1 (create schema), task 2 (implement repository, depends on 1), task 3 (add API endpoint, depends on 2)
- WHEN the tasks are added to the Plan
- THEN the DAG is valid
- AND task 1 is immediately unblocked

#### Scenario: Cross-spec dependency

- GIVEN task 5 from spec A depends on task 2 from spec B
- WHEN task 2 completes
- THEN task 5 becomes eligible for execution (assuming no other unsatisfied dependencies)

#### Scenario: Cyclic dependency rejected

- GIVEN task 1 depends on task 2, and task 2 depends on task 1
- WHEN the tasks are submitted
- THEN the system SHALL reject the dependency set

### Requirement: Unsatisfiable Dependencies

When a task's dependency target is in a superseded SpecPlan (the dependency will never be satisfied), the task SHALL be immediately marked as Failed with reason "dependency invalidated." Retries are not attempted because retrying cannot resolve a missing dependency.

#### Scenario: Dependency superseded

- GIVEN task B (spec X) depends on task A (spec Y)
- WHEN spec Y receives a new blob SHA and its old SpecPlan is superseded
- THEN task A is in a superseded SpecPlan
- AND task B SHALL be immediately marked Failed with reason DependencyInvalidated
- AND no retries are attempted for task B

#### Scenario: Dependency in Failed spec stays blocked

- GIVEN task B (spec X) depends on task A (spec Y)
- WHEN spec Y transitions to Failed (but is not superseded)
- THEN task A has status Failed but its SpecPlan is not superseded
- AND task B remains blocked (not failed)
- AND task B waits until spec Y is either updated (superseding the old SpecPlan) or otherwise resolved

#### Scenario: Cascade to re-decomposition

- GIVEN task B was failed due to DependencyInvalidated
- WHEN the task failure handling rules are applied
- THEN task B's failure counts toward the re-decomposition trigger for spec X
- AND spec X is re-decomposed if the re-decomposition budget allows
- AND the re-decomposition agent can reference spec Y's new tasks for correct dependencies

### Requirement: Task Failure and Retry

When a task fails, it SHALL be retried with all failure events passed as context to the inner loop agent. The system SHALL enforce a configurable maximum retry count per task.

#### Scenario: Task retry with context

- GIVEN task 3 failed with a TaskFailed event containing the failure details
- WHEN the task is retried
- THEN the inner loop agent receives the task briefing including all prior failure events
- AND the failure context is available to inform the agent's approach

#### Scenario: Retry count enforced

- GIVEN a task with a configured max retry count of 3
- WHEN the task has been retried 3 times and fails again
- THEN the task's retries are exhausted
- AND re-decomposition handling is triggered

### Requirement: Re-Decomposition on Retry Exhaustion

When a task exhausts its retry limit, the spec SHALL be sent back to the decomposition agent exactly once for the current reconciliation attempt. If re-decomposed tasks also exhaust their retry limits, the spec SHALL transition to Failed.

#### Scenario: Re-decomposition after retry exhaustion

- GIVEN task 3 has exhausted its retry limit
- WHEN re-decomposition is triggered for the parent spec
- THEN the decomposition agent receives all failure events from all tasks
- AND it MAY produce a different set of tasks to achieve the same spec requirements
- AND the spec remains in Reconciling state

#### Scenario: Re-decomposed tasks also fail

- GIVEN a spec was re-decomposed and the new tasks also exhaust their retry limits
- WHEN re-decomposition is evaluated again
- THEN the spec SHALL transition to Failed (re-decomposition is allowed only once per reconciliation attempt)
- AND a human intervention event is recorded with accumulated failure context

### Requirement: Concurrent Task Execution

Unblocked tasks with no unsatisfied dependencies MAY be executed concurrently.

#### Scenario: Independent tasks run in parallel

- GIVEN tasks 2 and 3 both depend only on task 1, and task 1 is Complete
- WHEN the scheduler selects unblocked tasks
- THEN both tasks 2 and 3 are eligible for concurrent dispatch

#### Scenario: Dependent tasks run sequentially

- GIVEN task 3 depends on task 2
- WHEN task 2 is InProgress
- THEN task 3 is NOT eligible for dispatch
- AND task 3 becomes eligible only after task 2 reaches Complete
