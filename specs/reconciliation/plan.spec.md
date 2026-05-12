# Plan Specification

## Purpose

Defines the data model for tracking reconciliation state. The Plan is the central data structure that records which specs are being reconciled, what tasks exist, what events have occurred, and what work remains. All reconciliation decisions are derived from the Plan's current state.

## Requirements

### Requirement: Plan Structure

The Plan SHALL contain a collection of SpecPlans and a collection of plan-level Events.

#### Scenario: Plan reflects repository state

- GIVEN a repository with specs "auth.spec.md" and "users.spec.md"
- WHEN both specs are detected by the reconciler
- THEN the Plan SHALL contain one SpecPlan per spec per active blob SHA

#### Scenario: Plan-level events

- GIVEN a system-wide event occurs (e.g., reconciler started, convergence bound configuration changed)
- WHEN the event is recorded
- THEN it SHALL be attached to the Plan, not to any individual SpecPlan

### Requirement: SpecPlan

A SpecPlan SHALL be uniquely identified by the combination of spec path and blob SHA. A SpecPlan SHALL contain:

| Field | Description |
|---|---|
| path | File path of the spec relative to the repository root |
| blob_sha | Content-addressable identifier for the exact spec version |
| status | Current reconciliation state (OutOfSync, Reconciling, Verifying, Synced, Failed) |
| superseded | Whether this SpecPlan has been superseded by a newer blob SHA |
| reconciliation_attempts | Number of times this spec has cycled through verification failure back to OutOfSync |
| redecomposition_count | Number of re-decompositions performed for the current reconciliation attempt |
| tasks | Implementation tasks for this spec version |
| events | Domain events recorded against this spec version |

#### Scenario: Same spec path, different SHAs

- GIVEN "auth.spec.md" was modified while being reconciled
- WHEN the Plan is examined
- THEN it contains two SpecPlans for "auth.spec.md": one at the old SHA (superseded) and one at the new SHA (OutOfSync)

#### Scenario: Reconciliation attempts track verification cycles

- GIVEN a SpecPlan with reconciliation_attempts of 0
- WHEN the spec cycles through Verifying back to OutOfSync (verification failure)
- THEN reconciliation_attempts SHALL be incremented to 1

#### Scenario: Re-decomposition count resets on new verification cycle

- GIVEN a SpecPlan with redecomposition_count of 1 from a prior cycle
- WHEN the spec enters a new reconciliation attempt (after verification failure resets it to OutOfSync)
- THEN redecomposition_count SHALL be reset to 0

#### Scenario: SpecPlan identity is path plus SHA

- GIVEN a SpecPlan for ("auth.spec.md", abc123) exists
- WHEN a SpecPlan for ("auth.spec.md", def456) is added
- THEN these are two distinct SpecPlans
- AND they are not the same entity

### Requirement: Task

A Task SHALL contain:

| Field | Description |
|---|---|
| id | Unique monotonic integer ID across all specs in the Plan |
| depends_on | Task IDs this task depends on (forming a DAG) |
| spec_path | Path of the parent spec |
| spec_blob_sha | Content-addressable identifier of the parent spec version |
| name | Human-readable task name |
| description | What needs to be done |
| status | Current state: Backlog, InProgress, Complete, or Failed |
| events | Domain events recorded against this task |

#### Scenario: Task ID uniqueness across specs

- GIVEN spec A has tasks with IDs 1 and 2, and spec B has tasks with IDs 3 and 4
- WHEN a new task is created for spec A
- THEN its ID SHALL be 5 (the next monotonic value across all specs)

#### Scenario: Task status values

- GIVEN a task is created
- WHEN its status is set
- THEN it SHALL be one of: Backlog, InProgress, Complete, or Failed
- AND no other values are valid

### Requirement: Event

An Event SHALL contain:

| Field | Description |
|---|---|
| type | Normal or Warning |
| reason | Machine-readable event reason. The set of valid reasons is extensible; examples include TaskFailed, VerificationFailed, VerificationPassed, DependencyInvalidated, and DecompositionFailed |
| count | Number of times this event has occurred |
| first_timestamp | When this event first occurred |
| last_timestamp | When this event most recently occurred |
| message | Human-readable description |

#### Scenario: Event aggregation

- GIVEN a task has a TaskFailed event with count 1
- WHEN the same task fails again with the same reason
- THEN the existing event's count SHALL be incremented to 2
- AND last_timestamp SHALL be updated
- AND no duplicate event is created

#### Scenario: Different reasons create separate events

- GIVEN a task has a TaskFailed event
- WHEN the task fails with a different reason (e.g., MergeConflict vs. ImplementationError)
- THEN a new event is created for the new reason
- AND both events coexist on the task

### Requirement: Idempotent Spec Addition

Adding a spec to the Plan SHALL be idempotent. If a SpecPlan with the same (path, blob_sha) already exists, no change occurs. If one or more SpecPlans exist for the same path but different blob SHAs, all existing SpecPlans for that path with non-matching SHAs SHALL be marked as superseded.

#### Scenario: Adding a spec that already exists

- GIVEN the Plan contains a SpecPlan for ("auth.spec.md", abc123)
- WHEN add is called with ("auth.spec.md", abc123)
- THEN the Plan is unchanged

#### Scenario: Adding a spec with a new SHA supersedes old entries

- GIVEN the Plan contains a SpecPlan for ("auth.spec.md", abc123) with status Reconciling
- WHEN add is called with ("auth.spec.md", def456)
- THEN a new SpecPlan is created for ("auth.spec.md", def456) with status OutOfSync
- AND the SpecPlan for abc123 is marked as superseded

#### Scenario: Multiple old SHAs all superseded

- GIVEN the Plan contains SpecPlans for ("auth.spec.md", abc123) and ("auth.spec.md", bbb222)
- WHEN add is called with ("auth.spec.md", def456)
- THEN both abc123 and bbb222 are marked as superseded
- AND a new SpecPlan for def456 is created with status OutOfSync

### Requirement: Task Addition

When tasks are added to a SpecPlan, the SpecPlan's status SHALL transition to Reconciling. Each task SHALL reference its parent spec by path and blob SHA.

#### Scenario: Adding tasks sets status to Reconciling

- GIVEN a SpecPlan with status OutOfSync
- WHEN tasks are added to it
- THEN the SpecPlan's status SHALL transition to Reconciling

#### Scenario: Tasks reference their parent spec

- GIVEN a SpecPlan for ("auth.spec.md", abc123)
- WHEN task 7 is added to it
- THEN task 7's spec_path is "auth.spec.md" and spec_blob_sha is "abc123"

### Requirement: Monotonic Task IDs

The Plan SHALL provide a method to generate the next unique monotonic task ID. The ID space is shared across all SpecPlans in the Plan to ensure global uniqueness.

#### Scenario: IDs are globally unique

- GIVEN tasks 1-4 exist across multiple SpecPlans
- WHEN the next ID is requested
- THEN it returns 5
- AND no two tasks in the Plan ever share an ID

### Requirement: Unblocked Task Selection

The Plan SHALL provide a method to select tasks eligible for execution. A task is eligible when:

1. Its status is Backlog
2. All tasks in its depends_on list have status Complete
3. Its parent SpecPlan is not superseded

#### Scenario: Task with satisfied dependencies

- GIVEN task 3 depends on tasks 1 and 2
- WHEN tasks 1 and 2 both have status Complete
- THEN task 3 is included in unblocked task selection

#### Scenario: Task with unsatisfied dependencies

- GIVEN task 3 depends on tasks 1 and 2
- WHEN task 1 has status Complete but task 2 has status InProgress
- THEN task 3 is NOT included in unblocked task selection

#### Scenario: Superseded parent excludes tasks

- GIVEN a SpecPlan marked as superseded with tasks in Backlog
- WHEN unblocked task selection runs
- THEN no tasks from the superseded SpecPlan are returned

#### Scenario: Cross-spec dependency

- GIVEN task 5 (spec A) depends on task 2 (spec B)
- WHEN task 2 has status Complete
- THEN task 5 is eligible (assuming its other dependencies are also satisfied and its parent is not superseded)

### Requirement: Plan Persistence

The Plan SHALL be persisted and retrieved through the PlanStore port. The system MUST NOT assume any specific storage mechanism.

#### Scenario: Plan survives restart

- GIVEN a Plan with 3 SpecPlans and 12 tasks
- WHEN the system restarts
- THEN the Plan is retrieved from the PlanStore with all state intact

#### Scenario: Plan persistence is atomic

- GIVEN the Plan has been modified (tasks added, statuses changed)
- WHEN persist is called
- THEN all changes are durably committed as a single unit
- AND a partial write SHALL NOT leave the Plan in an inconsistent state
