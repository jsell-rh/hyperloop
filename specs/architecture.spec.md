# Architecture Specification

## Purpose

Hyperloop is a spec-to-code reconciler. Specs declare desired behavior (desired state). Code is actual behavior (actual state). Hyperloop continuously detects gaps between the two and dispatches AI agents to close them.

The system follows the Kubernetes reconciliation model: observe desired state, observe actual state, take one step to converge. Specs are the persistent artifact. Tasks are ephemeral vehicles for closing gaps.

## Requirements

### Requirement: Spec-Driven Reconciliation

The system SHALL treat spec files as desired state and code as actual state. All work MUST originate from a detected gap between specs and code. The only way to create work is to write or modify a spec. The only way to stop work is to change or remove a spec.

#### Scenario: New spec creates work

- GIVEN a new spec file is committed to the repository
- WHEN the reconciler runs
- THEN it detects the spec has no matching tasks
- AND dispatches the PM agent to create tasks

#### Scenario: Spec modification creates new work

- GIVEN a spec has been fully implemented (all tasks synced)
- WHEN the spec file is modified
- THEN the reconciler detects the SHA drift
- AND dispatches the PM agent to create tasks for the changes

#### Scenario: No spec change means no work

- GIVEN all specs are covered by tasks pinned to current SHAs
- WHEN the reconciler runs
- THEN no new work is created

### Requirement: Two-Subsystem Separation

The system SHALL consist of two distinct subsystems: a **reconciler** and a **task processor**.

The reconciler determines what work needs to exist. It creates and retires tasks, detects drift, runs the PM agent, and audits alignment. The task processor walks tasks through configured phases. It spawns workers, advances phases on results, and handles retries.

Neither subsystem SHALL assume knowledge of the other's internals.

#### Scenario: Reconciler creates, task processor executes

- GIVEN the reconciler creates a task for spec "auth.md"
- WHEN the task processor picks up the task
- THEN the task processor walks it through phases without knowing why it was created
- AND the reconciler monitors convergence without knowing which phase the task is in

#### Scenario: Subsystems share only the state store

- GIVEN the reconciler writes a new task to the state store
- WHEN the task processor reads tasks from the state store
- THEN the task processor sees the new task and begins processing it
- AND no direct communication occurs between the subsystems

### Requirement: Data Model - Task

A task SHALL be an immutable value object containing:

| Field | Type | Description |
|---|---|---|
| id | string | Unique identifier |
| title | string | Human-readable description |
| spec_ref | string | Spec path with SHA pin (e.g., `specs/auth.md@abc123`) |
| status | enum | `not-started`, `in-progress`, `completed`, `failed` |
| phase | string or null | Current phase name in the phase map |
| deps | ordered list of string | Task IDs this task depends on |
| round | integer | Iteration count, incremented on retry |
| branch | string or null | Git branch for this task's work |
| pr | string or null | Pull request URL |

#### Scenario: Spec ref is always SHA-pinned

- GIVEN the PM creates a task for spec "auth.md"
- WHEN the current HEAD SHA is abc123
- THEN the task's spec_ref MUST be "specs/auth.md@abc123"
- AND the spec content used in prompts MUST be read at that exact SHA

#### Scenario: Task status lifecycle

- GIVEN a new task
- WHEN it is created by the PM
- THEN its status is "not-started" and phase is null
- AND on first spawn it transitions to "in-progress"
- AND on successful completion of all phases it transitions to "completed"
- AND on terminal failure it transitions to "failed"

### Requirement: Data Model - Worker Result

A worker result SHALL contain:

| Field | Type | Description |
|---|---|---|
| verdict | enum | `pass` or `fail` |
| detail | string | Free-text explanation |

Workers report verdicts. The orchestrator decides status transitions. Workers MUST NOT write task status directly.

### Requirement: Data Model - Step Result

A step result SHALL contain:

| Field | Type | Description |
|---|---|---|
| outcome | enum | `advance`, `retry`, `wait` |
| detail | string | Human-readable explanation of the outcome |
| pr_url | string or null | Updated PR URL if the step created or recreated a PR |

Step results are returned by the StepExecutor and derived from worker verdicts and signal statuses. The detail field provides context for retry/wait outcomes (e.g., "CI checks pending", "merge conflict").

### Requirement: Data Model - Phase Map

The phase map SHALL define the task workflow as a flat mapping of phase names to step definitions. Each phase specifies:

| Field | Type | Description |
|---|---|---|
| run | string | Step type and name (e.g., `agent implementer`, `action merge`) |
| on_pass | string | Phase to transition to on ADVANCE, or "done" |
| on_fail | string | Phase to transition to on RETRY |
| on_wait | string | Phase to stay at when pending (defaults to self) |
| args | dict | Arguments passed to the step executor (optional) |

#### Scenario: Loop as backward transition

- GIVEN phases: implement, verify, merge
- WHEN verify's on_fail is "implement"
- THEN a verification failure loops back to implementation
- AND no loop primitive is needed

#### Scenario: Gate as self-transition

- GIVEN a phase "await-review" with on_wait: "await-review"
- WHEN the signal check returns pending
- THEN the task stays at "await-review"
- AND is re-evaluated next cycle

#### Scenario: Independent failure routing per phase

- GIVEN phases: implement, verify, review, merge
- WHEN review fails
- THEN on_fail MAY point to "verify" (minor fix) instead of "implement" (full redo)
- AND each phase independently controls its failure target

### Requirement: Data Model - Signal

A signal SHALL contain:

| Field | Type | Description |
|---|---|---|
| status | enum | `approved`, `rejected`, `pending` |
| message | string | Free-text from the human or external system |

#### Scenario: Signal with feedback

- GIVEN a reviewer rejects a PR with comment "add timeout handling"
- WHEN the signal is read
- THEN status is "rejected" and message contains the reviewer's comment
- AND on retry, the message is composed into the next worker's prompt

#### Scenario: Signal with approval

- GIVEN a reviewer approves a PR with comment "looks good, minor nit on line 42"
- WHEN the signal is read
- THEN status is "approved" and message contains the comment
- AND the task advances to the next phase

### Requirement: Port-Based Architecture

The system SHALL define seven ports:

| Port | Responsibility |
|---|---|
| Runtime | Spawn, poll, reap worker agents; run trunk agents (PM, process-improver); run isolated auditors with verdict capture |
| StateStore | Persist and query tasks, reviews, epochs, summaries |
| SpecSource | Detect spec changes, read specs at pinned versions |
| StepExecutor | Execute mechanical steps with three outcomes |
| SignalPort | Poll for human/external signals with messages |
| ChannelPort | Send notifications to humans/external systems |
| Observer | Domain probe protocol — typed methods per observation point |

Adapters implement ports for specific technologies. The system MUST function correctly with any conforming adapter set.

#### Scenario: Runtime swap

- GIVEN the system uses a local agent SDK runtime
- WHEN the runtime is swapped for a cloud-based runtime
- THEN the reconciler and task processor operate identically
- AND only the worker execution environment changes

#### Scenario: Forge swap

- GIVEN the system uses GitHub adapters for StepExecutor, SignalPort, and ChannelPort
- WHEN the adapters are swapped for GitLab implementations
- THEN all reconciliation and task processing logic remains unchanged

### Requirement: Dependency Rule

Domain logic MUST import nothing from ports or adapters. Ports MUST import from domain only for type definitions. Adapters MUST import from ports and domain. The main loop imports everything and wires the object graph.

### Requirement: Single Instance Per Repository

The system SHALL run as a single orchestrator instance per repository. Team members interact through:

- **Specs** (git push): declare desired state
- **Reviews** (forge UI): provide signals at gates
- **Dashboard**: observe progress and issue control commands
- **Process config** (git push): customize prompts and phase maps

#### Scenario: Multi-user interaction

- GIVEN an orchestrator is running for repository X
- WHEN Alice commits a new spec and Bob reviews a PR
- THEN the orchestrator detects Alice's spec and creates tasks
- AND the orchestrator detects Bob's review and advances the gated task
- AND neither Alice nor Bob runs the orchestrator directly

### Requirement: Crash Recovery

The system MUST be resumable after a crash. On restart, it SHALL read persisted state, detect orphaned workers, and resume from recorded task phases.

#### Scenario: Restart after crash

- GIVEN the orchestrator crashes while 3 tasks are in-progress
- WHEN the orchestrator restarts
- THEN it reads all tasks from the state store
- AND detects orphaned workers for in-progress tasks without active sessions
- AND cancels orphaned workers
- AND re-enters the main loop, where the task processor respawns workers from current phases

#### Scenario: Idempotent reconciliation

- GIVEN the orchestrator runs a reconciler cycle
- WHEN it is immediately run again with no state changes
- THEN no new actions are taken
- AND the system is in the same state as before
