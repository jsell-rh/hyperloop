# Ports Specification

## Purpose

Ports define the behavior contracts between the system's core logic and external concerns. Each port is a protocol interface. Adapters implement ports for specific technologies. This spec defines what each port must do, not how.

## Requirements

### Requirement: Runtime Port

The Runtime port SHALL manage worker agent lifecycle and serial agent execution.

#### Scenario: Spawn a worker

- GIVEN a task with a branch and a composed prompt
- WHEN spawn is called with task_id, role, prompt, and branch
- THEN a worker agent is started in an isolated environment on that branch
- AND a worker handle is returned for tracking

#### Scenario: Poll a worker

- GIVEN an active worker handle
- WHEN poll is called
- THEN it returns one of: "running", "done", or "failed"
- AND no side effects occur

#### Scenario: Reap a completed worker

- GIVEN a worker with poll status "done"
- WHEN reap is called
- THEN it returns a WorkerResult with verdict and detail
- AND the worker's resources are cleaned up

#### Scenario: Cancel a worker

- GIVEN an active worker handle
- WHEN cancel is called
- THEN the worker is terminated
- AND its resources are cleaned up

#### Scenario: Find orphaned worker

- GIVEN the orchestrator crashed and restarted
- WHEN find_orphan is called with a task_id and branch
- THEN it returns a worker handle if an orphaned session exists for that task
- AND returns null if no orphan is found

#### Scenario: Run serial agent

- GIVEN a prompt for a serial agent (PM, auditor, process-improver)
- WHEN run_serial is called with role and prompt
- THEN the agent runs on the trunk branch, blocking until complete
- AND returns true on success, false on failure

#### Scenario: Push branch

- GIVEN a branch with local commits
- WHEN push_branch is called
- THEN the branch is pushed to the remote
- AND the operation is best-effort (no failure on missing remote)

#### Scenario: Worker epilogue

- GIVEN a runtime that requires workers to push their branches
- WHEN worker_epilogue is called
- THEN it returns runtime-specific instructions to append to worker prompts
- AND local runtimes return empty string (no push needed)

### Requirement: StateStore Port

The StateStore port SHALL persist and query orchestrator state including tasks, reviews, epochs, and summaries.

#### Scenario: Get world snapshot

- GIVEN tasks exist in the state store
- WHEN get_world is called
- THEN it returns a complete snapshot of all tasks and their current state

#### Scenario: Add a task

- GIVEN a new task created by the reconciler
- WHEN add_task is called
- THEN the task is persisted and visible in subsequent get_world calls

#### Scenario: Transition a task

- GIVEN task-001 with status "not-started"
- WHEN transition_task is called with status "in-progress" and phase "implement"
- THEN the task's status and phase are updated
- AND other fields remain unchanged

#### Scenario: Store review finding

- GIVEN a worker completed with findings for task-001, round 2
- WHEN store_review is called with task_id, round, role, verdict, and detail
- THEN the finding is persisted
- AND retrievable via get_findings

#### Scenario: Get latest findings

- GIVEN task-001 has reviews from rounds 0, 1, and 2
- WHEN get_findings is called
- THEN it returns the detail from the most recent round

#### Scenario: Reset a task

- GIVEN task-001 with a poisoned branch
- WHEN reset_task is called
- THEN status reverts to "not-started", phase to null, round to 0
- AND branch and pr are cleared
- AND identity fields (id, title, spec_ref, deps) are preserved

#### Scenario: Persist state

- GIVEN pending state changes
- WHEN persist is called with a commit message
- THEN all changes are durably committed

#### Scenario: Sync with remote

- GIVEN state that may have diverged from remote
- WHEN sync is called
- THEN local state is pulled from remote (with rebase)
- AND local state is pushed to remote

### Requirement: SpecSource Port

The SpecSource port SHALL detect spec changes and read spec content at pinned versions.

#### Scenario: Detect changes since version

- GIVEN specs have changed since version marker "abc123"
- WHEN detect_changes is called with since="abc123"
- THEN it returns a list of changed specs with change type (added, modified, deleted)

#### Scenario: First run detects all specs

- GIVEN no prior version marker exists
- WHEN detect_changes is called with since=null
- THEN it returns all spec files as "added"

#### Scenario: Read spec at pinned version

- GIVEN spec_ref "specs/auth.md@abc123"
- WHEN read is called
- THEN it returns the spec content as it existed at SHA abc123
- AND not the current HEAD version

#### Scenario: Current version marker

- GIVEN the repository is at HEAD SHA def456
- WHEN current_version is called
- THEN it returns "def456"

### Requirement: StepExecutor Port

The StepExecutor port SHALL execute mechanical steps (actions, checks) and return one of three outcomes.

#### Scenario: Successful step

- GIVEN a task at a "merge" action step
- WHEN execute is called with task, step name "merge", and args
- THEN it performs the merge operation
- AND returns ADVANCE on success

#### Scenario: Retriable failure

- GIVEN a merge step where the PR is not yet mergeable
- WHEN execute is called
- THEN it returns WAIT (re-check next cycle)

#### Scenario: Hard failure

- GIVEN a check step where CI has failed
- WHEN execute is called
- THEN it returns RETRY (loop back)

#### Scenario: Unknown step

- GIVEN a step name with no registered adapter
- WHEN execute is called
- THEN it returns RETRY with a descriptive error detail

### Requirement: SignalPort

The SignalPort port SHALL poll for human or external signals and return a Signal containing status and message.

#### Scenario: Approved signal

- GIVEN a reviewer has approved the PR for task-001
- WHEN check is called with task-001 and signal name "human-approval"
- THEN it returns Signal(status="approved", message="LGTM")

#### Scenario: Rejected signal with feedback

- GIVEN a reviewer has requested changes on the PR with comment "fix the null check"
- WHEN check is called
- THEN it returns Signal(status="rejected", message="fix the null check")

#### Scenario: Pending signal

- GIVEN no reviewer has responded yet
- WHEN check is called
- THEN it returns Signal(status="pending", message="")

#### Scenario: Multiple signal sources

- GIVEN a signal step configured to require reviews from both @coderabbit and @alice
- WHEN only @coderabbit has reviewed
- THEN it returns Signal(status="pending", message="awaiting review from @alice")

### Requirement: ChannelPort

The ChannelPort port SHALL send notifications to humans or external systems. It is outbound-only.

#### Scenario: Gate notification

- GIVEN task-001 enters a signal step "await-review"
- WHEN the channel sends a gate notification
- THEN a message is posted to the appropriate channel (PR comment, chat room, etc.)
- AND the message identifies the task, the gate, and what action is needed

#### Scenario: Error notification

- GIVEN task-001 has failed after max rounds
- WHEN the channel sends an error notification
- THEN a message is posted with the failure detail
- AND the message identifies the task and spec

#### Scenario: Deduplicated notifications

- GIVEN a gate notification was already sent for task-001 at phase "await-review"
- WHEN the task is still at the same phase next cycle
- THEN no duplicate notification is sent

### Requirement: Observer Port

The Observer port SHALL accept structured events via a single emit method. It MUST NOT raise exceptions.

#### Scenario: Event emission

- GIVEN an interesting moment occurs (worker spawned, task completed, etc.)
- WHEN emit is called with an event name and keyword arguments
- THEN the event is dispatched to all registered observer adapters

#### Scenario: Observer failure isolation

- GIVEN an observer adapter throws an exception
- WHEN emit is called
- THEN the exception is logged and swallowed
- AND other observer adapters still receive the event
- AND the orchestrator loop is not interrupted

#### Scenario: Multi-observer fan-out

- GIVEN three observer adapters are registered (log, chat, telemetry)
- WHEN an event is emitted
- THEN all three adapters receive the event
- AND adapter failures are independent
