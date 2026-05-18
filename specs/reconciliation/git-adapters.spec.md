# Git Adapters Specification

## Purpose

Defines how git implements the PlanStore, SpecSource, WorkspaceManager, and AgentRuntime ports. Git is the coordination substrate: branches organize work, commits carry status signals, and the repository is the shared state between the outer loop and inner loop agents. This spec captures the git-specific conventions that satisfy the abstract port contracts.

## Requirements

### Requirement: Branch Namespace

All branches created by the reconciler SHALL use the `hyperloop/` prefix to avoid collision with human-created branches. The branch hierarchy SHALL follow this structure:

| Branch | Purpose |
|---|---|
| `hyperloop/plan` | Plan state persistence |
| `hyperloop/spec/{blob_sha}/delivery` | Spec delivery branch (collects completed task work) |
| `hyperloop/spec/{blob_sha}/task/{task_id}` | Task work branch (individual unit of work) |
| `hyperloop/spec/{blob_sha}/verifier` | Verification agent workspace |

#### Scenario: Branch naming for a new spec

- GIVEN a spec "auth.spec.md" at blob SHA abc123 with tasks 5 and 6
- WHEN the reconciler creates workspaces
- THEN the following branches are created:
  - `hyperloop/spec/abc123/delivery` (delivery branch)
  - `hyperloop/spec/abc123/task/5` (task 5 work)
  - `hyperloop/spec/abc123/task/6` (task 6 work)

#### Scenario: No collision with human branches

- GIVEN a developer has branches `main`, `feature/auth`, and `bugfix/login`
- WHEN the reconciler creates its branches
- THEN all reconciler branches are under `hyperloop/`
- AND no human branches are affected

### Requirement: PlanStore via Git Branch

The git PlanStore adapter SHALL persist the Plan as a JSON file (`plan.json`) on the `hyperloop/plan` branch. This branch is an orphan branch (no shared history with trunk) containing only the plan file.

#### Scenario: Read the Plan

- GIVEN `plan.json` exists on the `hyperloop/plan` branch
- WHEN get_plan is called
- THEN the adapter pulls the `hyperloop/plan` branch
- AND reads and deserializes `plan.json`
- AND returns the complete Plan

#### Scenario: Write the Plan

- GIVEN the Plan has been modified
- WHEN write_plan is called
- THEN the adapter pulls the `hyperloop/plan` branch (to pick up any remote changes)
- AND serializes the Plan to `plan.json`
- AND commits the change
- AND pushes the `hyperloop/plan` branch

#### Scenario: First run with no plan branch

- GIVEN no `hyperloop/plan` branch exists
- WHEN get_plan is called for the first time
- THEN the adapter creates the orphan branch
- AND returns an empty Plan

#### Scenario: Atomic write via single commit

- GIVEN multiple Plan fields have changed
- WHEN write_plan is called
- THEN all changes are written to `plan.json` in a single commit
- AND pushed in a single push operation

### Requirement: SpecSource via Trunk

The git SpecSource adapter SHALL detect spec files on the trunk branch and provide content at pinned versions using git blob SHAs.

#### Scenario: List specs on trunk

- GIVEN trunk contains `specs/auth.spec.md` and `specs/users.spec.md`
- WHEN list_specs is called
- THEN it returns both paths with their current blob SHAs

#### Scenario: Read spec at pinned version

- GIVEN "specs/auth.spec.md" has been modified since blob SHA abc123
- WHEN read_at is called with ("specs/auth.spec.md", abc123)
- THEN it reads the file content at that exact blob SHA using `git show`
- AND returns the content as it existed at that version

#### Scenario: Diff between versions

- GIVEN "specs/auth.spec.md" at old SHA abc123 and new SHA def456
- WHEN diff is called
- THEN it returns the output of `git diff` between the two blob SHAs

#### Scenario: Sync with upstream

- GIVEN the remote has new commits on trunk
- WHEN sync is called
- THEN the adapter fetches and fast-forwards the local trunk ref

### Requirement: Spec Delivery Workspace

The git WorkspaceManager adapter SHALL use a dedicated branch per spec version as the delivery workspace — the "PR vehicle" that collects all completed task work and is eventually merged to trunk.

#### Scenario: Create delivery workspace

- GIVEN a spec entering Reconciling at blob SHA abc123
- WHEN create_delivery_workspace is called
- THEN a branch `hyperloop/spec/abc123/delivery` is created from the current trunk HEAD
- AND if the branch already exists, no action is taken (idempotent)

#### Scenario: Delivery branch is the PR vehicle

- GIVEN all tasks for abc123 are complete and verified
- WHEN integrate is called with a title, body, spec_path, and blob_sha
- THEN a pull request is opened from `hyperloop/spec/abc123/delivery` to trunk
- AND the PR uses the provided title and body

### Requirement: Task Workspace

The git WorkspaceManager adapter SHALL create a branch per task, branched from the spec delivery branch. Task branches are where inner loop agents perform their work.

#### Scenario: Create task workspace

- GIVEN task 5 for spec at blob SHA abc123
- WHEN create_task_workspace is called
- THEN a branch `hyperloop/spec/abc123/task/5` is created from `hyperloop/spec/abc123/delivery`

#### Scenario: Task briefing as empty commit

- GIVEN task 5 is being dispatched to the inner loop
- WHEN the workspace is prepared
- THEN an empty commit (no file changes) SHALL be created on the task branch
- AND the commit message SHALL contain the task details, spec reference, and relevant events
- AND this commit serves as the agent's briefing — the agent reads it to understand its assignment

#### Scenario: Merge completed task into delivery branch

- GIVEN task 5 has completed on branch `hyperloop/spec/abc123/task/5`
- WHEN merge_task is called
- THEN the task branch is merged into `hyperloop/spec/abc123/delivery`
- AND on success, the task branch is deleted (cleanup)
- AND on merge conflict, failure is returned for merge resolution handling

### Requirement: Verification Workspace

The git WorkspaceManager adapter SHALL create a verification branch from the spec delivery branch for the verification agent.

#### Scenario: Create verification workspace

- GIVEN a spec at blob SHA abc123 entering Verifying state
- WHEN the verification workspace is created
- THEN a branch `hyperloop/spec/abc123/verifier` is created from `hyperloop/spec/abc123/delivery`
- AND if the branch already exists, it is deleted and recreated (fresh verification)

#### Scenario: Cleanup after verification

- GIVEN the verification agent has completed (pass or fail)
- WHEN cleanup is called
- THEN the `hyperloop/spec/abc123/verifier` branch is deleted

### Requirement: Completion Signaling via Empty Commits

Inner loop agents and verification agents SHALL signal completion by creating an empty commit (no file changes) on their branch with a structured commit message. The AgentRuntime git adapter reads these commits to implement the poll operation.

#### Scenario: Task completion signal

- GIVEN task 5 has finished its work on branch `hyperloop/spec/abc123/task/5`
- WHEN the agent signals completion
- THEN the latest commit on the branch SHALL be an empty commit with the format:
  ```
  <Summary of work performed>

  Task-Status: Complete
  ```
- AND the AgentRuntime adapter parses this to return (Complete, summary) from poll

#### Scenario: Task failure signal

- GIVEN task 5 has failed
- WHEN the agent signals failure
- THEN the latest commit on the branch SHALL be an empty commit with the format:
  ```
  <Rationale for failure>

  Task-Status: Failed
  ```
- AND the AgentRuntime adapter parses this to return (Failed, rationale) from poll

#### Scenario: Verification pass signal

- GIVEN the verification agent confirms alignment
- WHEN it signals completion on `hyperloop/spec/abc123/verifier`
- THEN the latest commit SHALL be an empty commit with the format:
  ```
  <Assessment rationale>

  Verification-Status: Pass
  ```

#### Scenario: Verification fail signal

- GIVEN the verification agent finds misalignment
- WHEN it signals failure
- THEN the latest commit SHALL be an empty commit with the format:
  ```
  <Detailed rationale for misalignment>

  Verification-Status: Fail
  ```

#### Scenario: No signal yet (agent still running)

- GIVEN an agent is still working on its branch
- WHEN the AgentRuntime adapter polls the branch
- THEN the latest commit is NOT an empty commit matching the signal format
- AND poll returns Running

### Requirement: Polling via Git Fetch

The AgentRuntime git adapter SHALL implement poll by fetching the remote branch and reading the latest commit. This is a read-only operation with no side effects beyond updating the local ref.

#### Scenario: Poll a running task

- GIVEN task 5 is in progress
- WHEN poll is called
- THEN the adapter fetches `hyperloop/spec/abc123/task/5` from the remote
- AND reads the latest commit
- AND if the commit does not match the completion signal format, returns Running

#### Scenario: Poll a completed task

- GIVEN task 5 has signaled completion
- WHEN poll is called
- THEN the adapter fetches the branch
- AND reads the latest commit
- AND parses the Task-Status trailer
- AND returns (Complete, rationale) for Task-Status: Complete, or (Failed, rationale) for Task-Status: Failed

#### Scenario: Poll a completed verification agent (pass)

- GIVEN the verification agent on `hyperloop/spec/abc123/verifier` has signaled pass
- WHEN poll is called
- THEN the adapter fetches the branch and reads the latest commit
- AND parses the Verification-Status trailer
- AND returns (Complete, verdict=Pass, rationale) for Verification-Status: Pass

#### Scenario: Poll a completed verification agent (fail)

- GIVEN the verification agent on `hyperloop/spec/abc123/verifier` has signaled fail
- WHEN poll is called
- THEN the adapter parses Verification-Status: Fail
- AND returns (Complete, verdict=Fail, rationale)
- AND it does NOT return Failed — the agent completed successfully, it just found misalignment

### Requirement: Stale Branch Detection

The AgentRuntime git adapter SHALL detect stale agent branches after a crash by scanning for task and verification branches that have no completion signal.

#### Scenario: Detect stale task agent branch

- GIVEN the reconciler crashed while task 5 was InProgress on branch `hyperloop/spec/abc123/task/5`
- WHEN detect_stale is called
- THEN the adapter scans for branches matching `hyperloop/spec/*/task/*`
- AND for each, checks whether the latest commit matches the completion signal format
- AND returns handles for branches with no completion signal (agents still running or crashed)
- AND the reconciler cross-references these handles against InProgress tasks in the Plan to filter out stale branches from prior runs

#### Scenario: Detect stale verification agent branch

- GIVEN the reconciler crashed while verification was running on `hyperloop/spec/abc123/verifier`
- WHEN detect_stale is called
- THEN the adapter detects the verifier branch with no completion signal
- AND returns a handle for it

### Requirement: Cancellation via Branch Deletion

The AgentRuntime git adapter SHALL cancel an agent by deleting its branch. If the agent is running remotely, the branch deletion serves as a signal that its work is no longer needed.

#### Scenario: Cancel a running task agent

- GIVEN task 5 is running on branch `hyperloop/spec/abc123/task/5`
- WHEN cancel is called
- THEN the branch is deleted (both local and remote refs)
- AND any workspace resources associated with the branch are cleaned up

#### Scenario: Cancel a running verification agent

- GIVEN a verification agent is running on `hyperloop/spec/abc123/verifier`
- WHEN cancel is called
- THEN the verifier branch is deleted

### Requirement: Trunk Integration

The git WorkspaceManager adapter SHALL integrate verified spec work to trunk using the configured integration strategy. The pull request title and body are provided by the caller — the adapter SHALL NOT generate them.

#### Scenario: PR strategy integration

- GIVEN integration_strategy is "pr"
- WHEN integrate is called with blob_sha, spec_path, title, and body
- THEN a pull request is opened from `hyperloop/spec/{blob_sha}/delivery` to trunk
- AND the PR uses the provided title and body
- AND the PR URL is returned as the integration identifier

#### Scenario: PR automerge strategy integration

- GIVEN integration_strategy is "pr_automerge"
- WHEN integrate is called
- THEN a pull request is opened from the delivery branch to trunk with automerge enabled
- AND the PR URL is returned as the integration identifier

#### Scenario: Direct strategy integration

- GIVEN integration_strategy is "direct"
- WHEN integrate is called
- THEN the delivery branch is merged into trunk locally
- AND the merge commit is pushed to the remote
- AND a synthetic integration identifier is returned

#### Scenario: Direct merge conflict

- GIVEN integration_strategy is "direct" and trunk has diverged
- WHEN the local merge produces a conflict
- THEN integrate returns failure
- AND the reconciler handles this through the rebase and re-verification path

### Requirement: Integration Status Polling

The git WorkspaceManager adapter SHALL poll integration status by checking the state of the pull request or push result identified by the integration identifier.

#### Scenario: Poll pending PR

- GIVEN a PR is open and not yet merged
- WHEN poll_integration is called with the PR URL
- THEN it returns Pending

#### Scenario: Poll merged PR

- GIVEN a PR has been merged
- WHEN poll_integration is called with the PR URL
- THEN it returns Merged

#### Scenario: Poll PR with merge conflict

- GIVEN a PR cannot be merged due to conflicts
- WHEN poll_integration is called
- THEN it returns Conflict with details about the conflicting files

#### Scenario: Poll closed PR (not merged)

- GIVEN a PR was closed without merging
- WHEN poll_integration is called
- THEN it returns Failed

#### Scenario: Poll after direct integration

- GIVEN integration_strategy is "direct" and the push succeeded
- WHEN poll_integration is called with the synthetic identifier
- THEN it returns Merged (direct integration is synchronous)

### Requirement: Delivery Branch Rebase

The git WorkspaceManager adapter SHALL rebase a spec's delivery branch onto the current trunk HEAD when a trunk merge conflict is detected.

#### Scenario: Clean rebase

- GIVEN the delivery branch for blob SHA abc123 has diverged from trunk
- WHEN rebase_delivery is called
- THEN the adapter rebases `hyperloop/spec/abc123/delivery` onto the current trunk HEAD
- AND pushes the rebased branch
- AND returns Success

#### Scenario: Rebase conflict

- GIVEN the delivery branch and trunk have incompatible changes
- WHEN rebase_delivery is called and the rebase cannot complete automatically
- THEN the adapter aborts the rebase
- AND returns Conflict with details about the conflicting files

### Requirement: Cleanup on Supersede

When a spec is superseded or deleted, the git WorkspaceManager adapter SHALL delete all associated branches.

#### Scenario: Full cleanup on supersede

- GIVEN spec at blob SHA abc123 is superseded by def456
- WHEN cleanup is called for abc123
- THEN branches `hyperloop/spec/abc123/delivery`, `hyperloop/spec/abc123/task/*`, and `hyperloop/spec/abc123/verifier` are deleted
- AND both local and remote refs are cleaned up

#### Scenario: Plan branch is never cleaned up

- GIVEN the `hyperloop/plan` branch exists
- WHEN any cleanup operation runs
- THEN the plan branch is never deleted
- AND it persists for the lifetime of the repository
