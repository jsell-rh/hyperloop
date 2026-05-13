# Agent Executor Specification

## Purpose

Agent executors implement the mechanism for starting, monitoring, and stopping inner loop agents. The executor is a pluggable strategy behind the AgentRuntime adapter — it handles the *how* of running agents while the AgentRuntime handles the *what* (git coordination, prompt composition, signal parsing). Two executors are specified: a Claude Agent SDK executor (local, in-process) and an Ambient Code Platform executor (remote, session-based).

## Requirements

### Requirement: Asynchronous Agent Execution

The executor SHALL start task and verification agents asynchronously. The caller provides a branch, prompt, and optional model. The executor starts the agent and returns immediately. Actionable completion detection (state transitions in the reconciler) is NOT the executor's responsibility — the AgentRuntime handles that via git polling.

#### Scenario: Start a task agent

- GIVEN a branch "hyperloop/spec/abc123/task/5" exists
- WHEN start_task_agent is called with the branch, a composed prompt, and an optional model
- THEN an agent is started with the provided prompt in an isolated context associated with the branch
- AND the method returns immediately (does not block until agent completion)

#### Scenario: Start a verification agent

- GIVEN a branch "hyperloop/spec/abc123/verifier" exists
- WHEN start_verification_agent is called with the branch, a composed prompt, and an optional model
- THEN a verification agent is started with the provided prompt in an isolated context
- AND the method returns immediately

### Requirement: Synchronous Agent Execution

The executor SHALL run decomposition, merge resolution, and integration summary agents synchronously. These calls block until the agent completes and return structured results. Synchronous agents MUST create a temporary workspace, run the agent, parse the output, and clean up the workspace before returning. Synchronous operations SHALL enforce a configurable timeout. If the timeout is exceeded, the operation SHALL raise a timeout error. Timeout errors are distinct from transient failures and MUST NOT be retried.

#### Scenario: Run decomposition

- GIVEN out-of-sync specs need decomposition into tasks
- WHEN run_decomposition is called with a prompt and optional model
- THEN the executor creates a temporary workspace for the agent
- AND the agent runs to completion (blocking)
- AND the executor parses the agent's output into proposed tasks
- AND the temporary workspace is cleaned up before returning
- AND the proposed tasks are returned to the caller

#### Scenario: Resolve merge conflict

- GIVEN a merge conflict between a task branch and a delivery branch
- WHEN resolve_merge is called with both branch names, a prompt, and optional model
- THEN the executor runs an agent with access to both branches
- AND the agent attempts to resolve the conflict
- AND the call blocks until resolution completes
- AND returns true on success, false on failure

#### Scenario: Compose integration summary

- GIVEN a spec has passed verification and needs a PR description
- WHEN compose_summary is called with a prompt and optional model
- THEN the executor creates a temporary workspace for the agent
- AND the agent generates a title and body (blocking)
- AND the executor parses the output into an integration summary
- AND the temporary workspace is cleaned up before returning

#### Scenario: Sync operation timeout

- GIVEN run_decomposition is called and the agent does not complete within the configured timeout
- WHEN the timeout is exceeded
- THEN the operation raises a timeout error
- AND the agent is terminated and its temporary workspace is cleaned up

### Requirement: Transient Failure Retry

All executor operations (agent start, session creation, branch push) SHALL retry on transient failures with exponential backoff. Timeout errors SHALL NOT be retried. The maximum number of retry attempts SHALL be configurable.

#### Scenario: Transient failure during agent start

- GIVEN start_task_agent is called and the first attempt fails with a transient error
- WHEN the executor retries
- THEN it retries with exponential backoff
- AND succeeds on a subsequent attempt

#### Scenario: Timeout error is not retried

- GIVEN run_decomposition exceeds its timeout
- WHEN the timeout error is raised
- THEN the executor does NOT retry the operation
- AND the error propagates to the caller

### Requirement: Cancellation

The executor SHALL support cancellation of running agents via a cancel method that accepts a branch identifier. Cancellation terminates the agent and cleans up all executor-owned resources (worktrees, sessions, processes). Cancellation MUST NOT delete or modify git branches — branch lifecycle is the AgentRuntime's responsibility. The AgentRuntime's cancel operation is a two-step choreography: it calls the executor's cancel to clean up execution resources, then deletes the git branch itself.

#### Scenario: Cancel a running task agent

- GIVEN a task agent is running on branch "hyperloop/spec/abc123/task/5"
- WHEN cancel is called with the branch
- THEN the agent process or session is terminated
- AND all executor-owned resources for that branch are cleaned up
- AND the git branch is NOT deleted (the AgentRuntime handles that separately)

#### Scenario: Cancellation choreography

- GIVEN the AgentRuntime needs to cancel an agent on branch "hyperloop/spec/abc123/task/5"
- WHEN the AgentRuntime initiates cancellation
- THEN it first calls the executor's cancel to stop the agent and clean up execution resources
- AND then it deletes the git branch (local and remote)

#### Scenario: Idempotent cancellation

- GIVEN cancel was already called for a branch
- WHEN cancel is called again for the same branch
- THEN the call succeeds without error (no-op)

### Requirement: Stale Resource Recovery

The executor SHALL support detection of stale resources left behind by a process crash. Stale resource detection operates independently from the AgentRuntime's stale branch detection — the executor detects its own resources (worktrees, sessions), while the AgentRuntime detects stale git branches. Both are invoked independently during recovery.

#### Scenario: Detect stale executor resources

- GIVEN the orchestrator process crashed while agents were running
- WHEN detect_stale is called after restart
- THEN the executor returns a list of branch identifiers associated with stale resources
- AND these branches can be passed to cancel for cleanup

### Requirement: Execution Isolation

Agents MUST execute in isolated contexts. An agent's execution context MUST NOT interfere with the main repository, other running agents, or the orchestrator process.

#### Scenario: Parallel agent isolation

- GIVEN two task agents are running concurrently on different branches
- WHEN both agents modify files
- THEN each agent's modifications are confined to its own execution context
- AND neither agent observes the other's changes

#### Scenario: Environment isolation

- GIVEN a local agent is started (Claude Agent SDK executor)
- WHEN the agent subprocess inherits the parent process environment
- THEN git-specific environment variables (GIT_DIR, GIT_INDEX_FILE, GIT_WORK_TREE, etc.) MUST NOT be inherited
- AND other environment variables (API keys, PATH, HOME) SHALL be inherited

### Requirement: Claude Agent SDK Executor

The Claude Agent SDK executor SHALL run agents locally using the Claude Agent SDK. Each async agent runs in a git worktree created from the specified branch. Worktree lifecycle (creation, cleanup) is fully managed by the executor — it is not exposed to the AgentRuntime.

#### Scenario: Worktree creation for async agent

- GIVEN start_task_agent is called with a branch
- WHEN the executor prepares the execution context
- THEN it creates a git worktree from the specified branch
- AND the agent runs with that worktree as its working directory
- AND the agent is started in the background (non-blocking)

#### Scenario: Temporary worktree for sync agents

- GIVEN run_decomposition is called
- WHEN the executor creates a temporary execution context
- THEN a temporary branch and worktree are created
- AND the agent runs in the worktree
- AND after completion, both the worktree and temporary branch are deleted

#### Scenario: Stale worktree detection

- GIVEN the process crashed while agents were running in worktrees
- WHEN detect_stale is called
- THEN the executor scans its worktree directory for stale worktrees
- AND returns the branch associated with each stale worktree

#### Scenario: Model selection

- GIVEN start_task_agent is called with model "claude-sonnet-4-6"
- WHEN the agent session is started
- THEN the session uses the specified model
- AND if model is None, the SDK default model is used

### Requirement: Ambient Code Platform Executor

The Ambient Code Platform executor SHALL run agents remotely as platform sessions. Sessions are created with the full prompt and a configured repository URL. The repository URL and project identifier are provided at construction time. The executor SHALL guarantee that all running sessions are stopped when the orchestrator process exits (whether cleanly or via crash), preventing sessions from continuing to consume platform resources.

#### Scenario: Branch push before session creation

- GIVEN start_task_agent is called with a branch
- WHEN the branch has not been pushed to the remote
- THEN the executor pushes the branch to the remote before creating the session
- AND if the push fails, the method raises an exception (no session is created with an unavailable branch)

#### Scenario: Session creation for async agent

- GIVEN start_task_agent is called with a branch that is available on the remote
- WHEN the executor creates the session
- THEN a session is created with the composed prompt and the configured repository URL
- AND the session name follows a predictable convention based on the branch name (for stale detection)
- AND the method returns immediately after session creation

#### Scenario: Session health monitoring

- GIVEN an async agent session is running on the platform
- WHEN the executor monitors the session
- THEN the executor tracks session health via platform events (SSE)
- AND health status is used for lifecycle management (detecting crashed sessions, triggering cleanup)
- AND health monitoring does NOT drive reconciler state transitions (that remains git polling's responsibility)

#### Scenario: Blocking execution for sync agents

- GIVEN run_decomposition is called
- WHEN the executor creates a session
- THEN it blocks until the session completes (monitoring via platform events)
- AND the result is parsed from the session output
- AND the session is stopped after completion

#### Scenario: Stale session detection

- GIVEN the process crashed while sessions were running
- WHEN detect_stale is called
- THEN the executor queries the platform for running sessions matching its naming convention
- AND returns the branch associated with each stale session

#### Scenario: Session cancellation

- GIVEN a session is running for a task agent
- WHEN cancel is called with the branch
- THEN the executor stops the session via the platform
- AND internal tracking state is cleaned up

#### Scenario: Process exit cleanup

- GIVEN sessions are running when the orchestrator process exits
- WHEN the process terminates
- THEN all tracked sessions are stopped
- AND platform resources are released

### Requirement: Executor Configuration

The Configuration model SHALL include fields for executor selection and operational parameters. These values govern which executor is used and how it behaves.

#### Scenario: Executor selection

- GIVEN the reconciler is starting
- WHEN the configuration specifies an executor type
- THEN the composition root constructs the corresponding executor
- AND if no executor type is specified, a default SHALL be used

#### Scenario: Timeout and retry configuration

- GIVEN the configuration includes executor_timeout_seconds and executor_max_retries
- WHEN a sync operation runs
- THEN the configured timeout is enforced
- AND transient failures retry up to the configured maximum

#### Scenario: Ambient-specific configuration

- GIVEN the Ambient Code Platform executor is selected
- WHEN the executor is constructed
- THEN a repository URL MUST be provided (the clone URL for the target repository)
- AND a project identifier MUST be provided (the platform project that owns the sessions)
- AND if either is missing, construction SHALL fail with a validation error
