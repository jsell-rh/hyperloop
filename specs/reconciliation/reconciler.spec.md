# Reconciler Specification

## Purpose

Defines the behavior of the outer reconciliation loop: the continuous process that detects spec divergence, coordinates task execution, and drives specs toward Synced state. The reconciler is the system's heartbeat. It owns the lifecycle of a reconciliation cycle but delegates all external interactions through ports.

## Requirements

### Requirement: Reconciliation Cycle

The reconciler SHALL execute a continuous loop. Each cycle performs the following steps in order:

1. Sync state from external sources (spec source, plan store)
2. Detect divergence (new, modified, or deleted specs)
3. Decompose OutOfSync specs into tasks (via decomposition agent)
4. Dispatch unblocked tasks to the inner loop
5. Collect completed and failed task results
6. Merge completed task work into spec delivery workspaces
7. Launch verification for specs with all tasks complete
8. Collect verification results and apply state transitions
9. Persist the updated Plan

#### Scenario: Full cycle with no drift

- GIVEN all specs are Synced and no spec files have changed
- WHEN a reconciliation cycle runs
- THEN divergence detection finds nothing
- AND no decomposition, dispatch, or verification occurs
- AND the Plan is unchanged

#### Scenario: New spec triggers full flow

- GIVEN a new spec "auth.spec.md" is committed
- WHEN reconciliation cycles run
- THEN the spec is detected as OutOfSync
- AND it is decomposed into tasks
- AND unblocked tasks are dispatched to the inner loop
- AND on subsequent cycles, completed tasks are merged into the delivery workspace
- AND when all tasks complete, verification is launched
- AND on verification pass, the implementation is integrated to trunk and the spec transitions to Synced

### Requirement: Divergence Detection

The reconciler SHALL detect divergence by comparing the spec files reported by the SpecSource port against the Plan. Divergence exists when:

- A spec's blob SHA has no corresponding SpecPlan (new or modified spec)
- A spec present in the Plan no longer exists in the SpecSource (deleted spec)

#### Scenario: New spec detected

- GIVEN a spec "users.spec.md" at SHA abc123 exists in the SpecSource
- WHEN the Plan has no SpecPlan for this path and SHA
- THEN the reconciler adds it to the Plan as OutOfSync via idempotent addition

#### Scenario: Modified spec detected

- GIVEN "auth.spec.md" is Synced at SHA abc123 in the Plan
- WHEN the SpecSource reports "auth.spec.md" at SHA def456
- THEN the reconciler adds ("auth.spec.md", def456) to the Plan
- AND idempotent addition marks the abc123 SpecPlan as superseded

#### Scenario: Deleted spec detected

- GIVEN "old-feature.spec.md" has a SpecPlan in the Plan
- WHEN the SpecSource no longer lists "old-feature.spec.md"
- THEN the reconciler marks the SpecPlan as superseded
- AND cancels all in-flight agents for this spec

### Requirement: Decomposition Dispatch

The reconciler SHALL invoke the decomposition agent for all OutOfSync specs. The decomposition agent runs serially and receives, for each spec:

- The spec content at the current blob SHA
- The diff from the last Synced blob SHA (if any) to the current blob SHA
- All events on the SpecPlan (including prior VerificationFailed and TaskFailed events)
- The current state of all tasks across all specs (for cross-spec dependency awareness)

#### Scenario: Decomposition with prior failure context

- GIVEN a spec returned to OutOfSync after verification failed with "timeout handling missing"
- WHEN the decomposition agent is invoked
- THEN it receives the VerificationFailed event with the rationale
- AND it produces targeted corrective tasks

#### Scenario: Decomposition creates tasks in the Plan

- GIVEN the decomposition agent produces tasks [5, 6, 7] for a spec
- WHEN the reconciler processes the result
- THEN the tasks are added to the Plan under the appropriate SpecPlan
- AND the SpecPlan transitions to Reconciling

### Requirement: Task Dispatch

The reconciler SHALL dispatch unblocked tasks to the inner loop. For each task being dispatched:

1. A task workspace SHALL be created via the WorkspaceManager port
2. A task briefing SHALL be prepared containing: task details, spec content at the pinned blob SHA, and all relevant events (including failure events from prior attempts)
3. The task status SHALL be set to InProgress in the Plan
4. The inner loop agent SHALL be launched via the AgentRuntime port

#### Scenario: Task briefing includes failure events on retry

- GIVEN task 3 is being retried after a previous failure
- WHEN the briefing is prepared
- THEN it includes all TaskFailed events from prior attempts
- AND the inner loop agent can use this context to avoid repeating mistakes

#### Scenario: Workspace isolation

- GIVEN tasks 2 and 3 are dispatched concurrently
- WHEN their workspaces are created
- THEN each task has its own isolated workspace
- AND changes in one workspace do not affect the other

### Requirement: Result Collection

Each cycle, the reconciler SHALL poll all InProgress tasks for completion and process the results.

#### Scenario: Completed task merged successfully

- GIVEN task 3 has status Complete
- WHEN the reconciler collects its result
- THEN it merges the task workspace into the spec delivery workspace via the WorkspaceManager port
- AND on success, the task workspace is cleaned up

#### Scenario: Merge conflict triggers resolution agent

- GIVEN merging task 3's workspace into the delivery workspace produces a conflict
- WHEN the reconciler detects the conflict
- THEN it launches a merge resolution agent via the AgentRuntime port
- AND if the merge agent succeeds, the merge is completed
- AND if the merge agent fails, the task is treated as Failed

#### Scenario: Failed task triggers retry

- GIVEN task 3 has status Failed with retry attempts remaining
- WHEN the reconciler collects the result
- THEN a TaskFailed event is recorded with the failure rationale
- AND the task is re-dispatched with all events as context

#### Scenario: Task retry exhaustion triggers re-decomposition

- GIVEN task 3 has exhausted its retry limit and the spec has not yet been re-decomposed
- WHEN the reconciler processes the exhausted task
- THEN the spec is sent back to the decomposition agent with all failure context
- AND the decomposition agent MAY produce a different set of tasks

#### Scenario: Re-decomposition exhaustion triggers Failed

- GIVEN a spec was already re-decomposed and the new tasks also exhausted their retries
- WHEN the reconciler evaluates the spec
- THEN the spec transitions to Failed

### Requirement: Verification

After all tasks for a SpecPlan reach Complete status, the reconciler SHALL launch a verification agent to assess whether the implementation matches the spec.

#### Scenario: Verification launched on completion

- GIVEN all tasks for spec "auth.spec.md" at SHA abc123 are Complete
- WHEN the reconciler evaluates the SpecPlan
- THEN the SpecPlan transitions to Verifying
- AND a verification agent is launched via the AgentRuntime port in a fresh session

#### Scenario: Verification pass

- GIVEN the verification agent returns Pass with rationale
- WHEN the reconciler collects the result
- THEN a VerificationPassed event is recorded
- AND the delivery workspace is integrated to trunk via the WorkspaceManager port
- AND on successful integration, the SpecPlan transitions to Synced

#### Scenario: Verification fail

- GIVEN the verification agent returns Fail with rationale "error handling does not cover network timeouts"
- WHEN the reconciler collects the result
- THEN a VerificationFailed event is recorded with the full rationale
- AND the SpecPlan transitions to OutOfSync
- AND the next decomposition cycle produces targeted corrective tasks informed by the rationale

#### Scenario: Verification fail exceeds convergence bound

- GIVEN the SpecPlan has cycled through verification failures up to the configured convergence bound
- WHEN the verification agent returns Fail again
- THEN the SpecPlan transitions to Failed

### Requirement: Superseding Cancellation

When a spec is superseded (new blob SHA detected while Reconciling or Verifying) or deleted, the reconciler SHALL cancel all in-flight agents for the old blob SHA.

#### Scenario: In-flight tasks cancelled on supersede

- GIVEN tasks 4 and 5 are InProgress for spec "auth.spec.md" at SHA abc123
- WHEN SHA def456 is detected and abc123 is superseded
- THEN the reconciler cancels agents for tasks 4 and 5 via the AgentRuntime port
- AND their workspaces are cleaned up via the WorkspaceManager port
- AND their results are discarded

#### Scenario: Verification cancelled on supersede

- GIVEN a verification agent is running for SHA abc123
- WHEN SHA def456 is detected
- THEN the verification agent is cancelled
- AND the SpecPlan for abc123 is marked superseded

### Requirement: Cross-Spec Dependency Invalidation

When a SpecPlan is superseded or deleted, the reconciler SHALL scan all non-superseded tasks across all other SpecPlans for dependencies that targeted tasks in the superseded SpecPlan. Any such task SHALL be immediately marked Failed with reason DependencyInvalidated.

#### Scenario: Superseding invalidates cross-spec dependencies

- GIVEN task B (spec X) depends on task A (spec Y)
- WHEN spec Y receives a new blob SHA and its SpecPlan is superseded
- THEN the reconciler detects that task B's dependency on task A is unsatisfiable
- AND task B is marked Failed with reason DependencyInvalidated
- AND task B's failure is handled through the normal task failure path (counting toward re-decomposition for spec X)

#### Scenario: Re-decomposition references new tasks

- GIVEN spec X was re-decomposed after task B was invalidated
- WHEN spec Y has already been re-decomposed with new tasks [10, 11, 12]
- THEN the decomposition agent for spec X can reference the new spec Y tasks
- AND the new tasks for spec X have correct dependencies on spec Y's current tasks

#### Scenario: Blocked task stays blocked until supersede

- GIVEN task B (spec X) depends on task A (spec Y) and spec Y is Failed (not superseded)
- WHEN the reconciler scans for unsatisfiable dependencies
- THEN task B is NOT marked as Failed
- AND task B remains blocked until spec Y is updated (which supersedes the old SpecPlan)

### Requirement: Single Instance Per Repository

The reconciler SHALL run as a single instance per repository. It is not designed for concurrent execution against the same Plan or spec source.

#### Scenario: No concurrent reconcilers

- GIVEN a reconciler instance is running for repository X
- WHEN reconciliation is requested
- THEN only one instance processes the repository at a time

### Requirement: Crash Recovery

The reconciler SHALL be resumable after a crash. On restart, it reads the persisted Plan, detects orphaned agents, cancels them, and resumes the reconciliation cycle from the persisted state.

#### Scenario: Restart after crash

- GIVEN the reconciler crashes while tasks are InProgress
- WHEN the reconciler restarts
- THEN it reads the Plan from the PlanStore
- AND detects orphaned agents via the AgentRuntime port
- AND cancels orphaned agents
- AND resumes the reconciliation cycle

#### Scenario: Idempotent cycles

- GIVEN the reconciler runs a cycle
- WHEN it is immediately run again with no external changes
- THEN no new actions are taken
- AND the Plan is in the same state as before
