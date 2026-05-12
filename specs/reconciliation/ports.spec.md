# Ports Specification

## Purpose

Ports define the behavioral contracts between the reconciliation engine's domain logic and external systems. Each port is a protocol interface. Adapters implement ports for specific technologies (git, CI systems, agent runtimes, cloud platforms, etc.). The reconciliation engine MUST function correctly with any conforming adapter set.

## Requirements

### Requirement: PlanStore Port

The PlanStore port SHALL persist and retrieve the reconciliation Plan.

#### Scenario: Retrieve the current Plan

- GIVEN a Plan has been previously persisted
- WHEN get_plan is called
- THEN it returns the complete Plan with all SpecPlans, tasks, and events

#### Scenario: Persist the Plan

- GIVEN the Plan has been modified
- WHEN write_plan is called
- THEN the Plan is durably persisted
- AND subsequent get_plan calls return the updated Plan

#### Scenario: Atomic persistence

- GIVEN a Plan with multiple pending changes
- WHEN write_plan is called
- THEN all changes are committed as a single atomic unit
- AND a partial write SHALL NOT leave the Plan in an inconsistent state

#### Scenario: Concurrent access

- GIVEN the PlanStore may be accessed across restarts
- WHEN get_plan is called after a restart
- THEN the most recently persisted Plan is returned

### Requirement: SpecSource Port

The SpecSource port SHALL detect spec files in the repository and provide their content at specific versions.

#### Scenario: List current specs

- GIVEN the repository contains spec files
- WHEN list_specs is called
- THEN it returns all spec file paths with their current blob SHAs

#### Scenario: Read spec at pinned version

- GIVEN a spec at path "auth.spec.md" was modified since blob SHA abc123
- WHEN read_at is called with ("auth.spec.md", abc123)
- THEN it returns the spec content as it existed at SHA abc123
- AND NOT the current version

#### Scenario: Diff between versions

- GIVEN a spec at path "auth.spec.md" previously Synced at SHA abc123, now at SHA def456
- WHEN diff is called with ("auth.spec.md", abc123, def456)
- THEN it returns the textual diff between the two versions

#### Scenario: Diff for new spec

- GIVEN a spec at path "users.spec.md" with no prior Synced SHA
- WHEN diff is called with ("users.spec.md", null, abc123)
- THEN it returns the full spec content at abc123

#### Scenario: Sync with upstream

- GIVEN the spec source tracks a remote repository
- WHEN sync is called
- THEN the local view is updated to reflect the latest upstream state

### Requirement: AgentRuntime Port

The AgentRuntime port SHALL manage agent lifecycle for decomposition, implementation, verification, and merge resolution. The inner loop is an opaque, pluggable executor behind this port.

#### Scenario: Launch decomposition agent

- GIVEN OutOfSync specs with their diffs, existing tasks, and events
- WHEN launch_decomposition is called
- THEN a decomposition agent is started with the provided context
- AND it runs serially (blocking until complete)
- AND it returns proposed tasks with names, descriptions, spec references, and dependency declarations

#### Scenario: Launch task agent

- GIVEN a task briefing with spec content (at pinned SHA), task description, events, and a workspace
- WHEN launch_task is called
- THEN an implementation agent is started in the provided workspace
- AND a handle is returned for tracking

#### Scenario: Poll an agent

- GIVEN an active handle (task or verification)
- WHEN poll is called
- THEN it returns one of: Running, Complete, or Failed
- AND if Complete or Failed, includes a rationale string
- AND if Complete, MAY include a verdict (Pass or Fail) for agents that produce assessments

#### Scenario: Poll distinguishes completion from crash

- GIVEN a verification agent that completes and finds misalignment
- WHEN poll is called
- THEN it returns Complete with verdict Fail and rationale describing the misalignment
- AND it does NOT return Failed (which indicates the agent itself crashed, not that it found problems)

#### Scenario: Launch verification agent

- GIVEN a spec (at pinned SHA) and the workspace containing the combined implementation
- WHEN launch_verification is called
- THEN a verification agent is started in a fresh session with no context from implementation agents
- AND a handle is returned for tracking (same as launch_task)
- AND when polled to completion, the result includes a verdict (Pass or Fail) with rationale

#### Scenario: Launch merge resolution agent

- GIVEN a merge conflict between a task workspace and the spec delivery workspace
- WHEN launch_merge_resolution is called with the conflict details
- THEN a merge agent attempts to resolve the conflict
- AND it returns success or failure

#### Scenario: Cancel an agent

- GIVEN an active agent handle
- WHEN cancel is called
- THEN the agent is terminated
- AND its resources are cleaned up

#### Scenario: Detect orphaned agents

- GIVEN the system crashed and restarted
- WHEN detect_orphans is called
- THEN it returns handles for any agents that were running before the crash
- AND these handles can be cancelled to clean up

### Requirement: WorkspaceManager Port

The WorkspaceManager port SHALL manage isolated workspaces for task execution and spec delivery.

#### Scenario: Create a task workspace

- GIVEN a task that needs an isolated workspace for implementation
- WHEN create_task_workspace is called with the spec delivery context
- THEN an isolated workspace is created
- AND the workspace identifier is returned

#### Scenario: Create a spec delivery workspace

- GIVEN a spec entering Reconciling state
- WHEN create_delivery_workspace is called
- THEN a workspace is created to collect the combined output of all tasks for this spec
- AND the workspace identifier is returned

#### Scenario: Merge task work into delivery workspace

- GIVEN a task has completed in its workspace
- WHEN merge_task is called with the task workspace and delivery workspace
- THEN the task's changes are merged into the delivery workspace
- AND returns success or failure (conflict)

#### Scenario: Integrate delivery workspace to trunk

- GIVEN a spec's delivery workspace with all verified work
- WHEN integrate is called
- THEN the changes are submitted for integration to trunk
- AND an integration identifier is returned

#### Scenario: Create a verification workspace

- GIVEN a spec entering Verifying state
- WHEN create_verification_workspace is called
- THEN a fresh workspace is created from the delivery workspace for verification
- AND if a verification workspace already exists, it is replaced (fresh verification session)
- AND the workspace identifier is returned

#### Scenario: Clean up workspaces

- GIVEN a task workspace or delivery workspace is no longer needed (task cancelled, spec superseded)
- WHEN cleanup is called
- THEN the workspace and its resources are removed

#### Scenario: Clean up verification workspace

- GIVEN the verification agent has completed (pass or fail)
- WHEN cleanup_verification is called
- THEN the verification workspace is removed
- AND the delivery workspace and task workspaces are preserved

### Requirement: Observer Port

The Observer port SHALL follow the domain probe pattern: one typed method per observation point. Each method has keyword-only arguments defining the exact schema for that event. The Observer MUST NOT be used for control flow; it is purely informational.

#### Scenario: Probe call

- GIVEN a domain-meaningful event occurs (spec detected, task dispatched, verification failed, etc.)
- WHEN the corresponding probe method is called
- THEN all registered observers receive the call

#### Scenario: Observer failure isolation

- GIVEN an observer throws an exception
- WHEN a probe method is called
- THEN the exception is caught and suppressed
- AND other observers still receive the call
- AND the reconciliation loop is NOT interrupted

#### Scenario: Multiple observers

- GIVEN three observers are registered (structured logger, chat notifier, metrics exporter)
- WHEN a probe method is called
- THEN all three receive the call independently
- AND one observer's failure does not affect the others

### Requirement: Dependency Rule

Domain logic MUST NOT import from ports or adapters. Ports MUST import from domain only for type definitions. Adapters MUST import from ports and domain. The composition root imports all layers and wires the object graph.

#### Scenario: Domain is self-contained

- GIVEN the domain logic (state machine, Plan operations, task lifecycle rules)
- WHEN examined for imports
- THEN it imports nothing from port or adapter modules

#### Scenario: Adapter satisfies a port

- GIVEN a port protocol (e.g., PlanStore)
- WHEN an adapter implements it
- THEN the adapter imports the port protocol and domain types
- AND the domain does not know the adapter exists
