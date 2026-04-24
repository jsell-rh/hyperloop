# Task Processor Specification

## Purpose

The task processor walks tasks through configured phases. It reads each task's current phase, executes the step defined for that phase, and transitions the task based on the outcome. It is a deterministic state machine: given the same task state and phase map, it produces the same action.

## Requirements

### Requirement: Phase Map Execution

The task processor SHALL read the phase map and, for each in-progress task, execute the step defined by the task's current phase.

#### Scenario: Agent step spawns worker

- GIVEN task-001 is at phase "implement" which runs `agent implementer`
- WHEN the task processor evaluates task-001
- THEN it composes a prompt for the implementer role
- AND spawns a worker agent on the task's branch
- AND the task remains at phase "implement" until the worker completes

#### Scenario: Mechanical step executes immediately

- GIVEN task-001 is at phase "merge" which runs `action merge`
- WHEN the task processor evaluates task-001
- THEN it calls the StepExecutor with step name "merge" and the task
- AND transitions the task based on the outcome in the same cycle

#### Scenario: Signal step polls condition

- GIVEN task-001 is at phase "await-review" which runs `signal human-approval`
- WHEN the task processor evaluates task-001
- THEN it calls the SignalPort with signal name "human-approval" and the task
- AND transitions based on the signal status

### Requirement: Three Outcomes

Every step execution SHALL produce one of three outcomes:

| Outcome | Meaning | Behavior |
|---|---|---|
| ADVANCE | Step succeeded | Transition to on_pass phase |
| RETRY | Step failed, try again | Transition to on_fail phase |
| WAIT | Not ready yet | Transition to on_wait phase (default: stay at current phase) |

#### Scenario: ADVANCE moves forward

- GIVEN task-001 is at phase "implement" with on_pass: "verify"
- WHEN the implementer worker completes with verdict PASS
- THEN the task transitions to phase "verify"

#### Scenario: RETRY loops back

- GIVEN task-001 is at phase "verify" with on_fail: "implement"
- WHEN the verifier worker completes with verdict FAIL
- THEN the task transitions to phase "implement"
- AND the task's round counter is incremented
- AND the failure detail is stored as a review finding

#### Scenario: WAIT stays put

- GIVEN task-001 is at phase "await-review" with on_wait: "await-review"
- WHEN the signal returns status "pending"
- THEN the task remains at phase "await-review"
- AND no round counter increment occurs
- AND the task is re-evaluated next cycle

### Requirement: Phase Transitions

Phase transitions SHALL update the task's phase field. When a step produces RETRY (verdict FAIL or signal rejected), the round counter SHALL be incremented. When a step produces ADVANCE (verdict PASS or signal approved), the round counter SHALL NOT be incremented. Round increments are determined by the step outcome, not by the direction of the transition.

#### Scenario: ADVANCE does not increment round

- GIVEN task-001 at phase "implement", round 0
- WHEN the step produces ADVANCE
- THEN task-001.phase becomes the on_pass target and round remains 0

#### Scenario: RETRY increments round

- GIVEN task-001 at phase "verify", round 0
- WHEN the step produces RETRY
- THEN task-001.phase becomes the on_fail target and round becomes 1

#### Scenario: Reaching terminal completion

- GIVEN task-001 at phase "merge" with on_pass: "done"
- WHEN the merge step returns ADVANCE
- THEN task-001.status transitions to "completed"
- AND task-001.phase becomes null
- AND "done" is a reserved keyword, not a phase name — it signals terminal success

### Requirement: Worker Lifecycle

For agent steps, the task processor SHALL manage worker lifecycle through spawn, poll, and reap operations via the Runtime port.

#### Scenario: Worker spawn

- GIVEN task-001 is at an agent step with no active worker
- WHEN the task processor evaluates it
- THEN it composes a prompt and spawns a worker via the Runtime port
- AND records the worker handle

#### Scenario: Worker still running

- GIVEN task-001 has an active worker
- WHEN the task processor polls the worker and it is still running
- THEN no action is taken
- AND the task is re-evaluated next cycle

#### Scenario: Worker completed

- GIVEN task-001 has an active worker that has finished
- WHEN the task processor polls the worker
- THEN it reaps the worker result via the Runtime port
- AND processes the verdict as ADVANCE (pass) or RETRY (fail)

#### Scenario: Failure detail stored as finding

- GIVEN a worker completes with verdict FAIL and detail "missing error handling"
- WHEN the task processor reaps the result
- THEN it stores the detail as a review finding in the state store
- AND the finding is composed into the prompt on the next attempt

#### Scenario: Worker crashes without writing verdict

- GIVEN a worker completes or is terminated without writing a verdict file
- WHEN the task processor reaps the result
- THEN the result defaults to FAIL with detail "worker completed without writing verdict"
- AND the probe emits worker_crash_detected with task_id, role, and branch
- AND the ChannelPort sends a notification to alert a human of the crash

### Requirement: Signal Handling at Gates

For signal steps, the task processor SHALL poll the SignalPort and handle all three signal statuses.

#### Scenario: Signal approved

- GIVEN task-001 is at a signal step
- WHEN the SignalPort returns status "approved"
- THEN the outcome is ADVANCE
- AND if the signal includes a message, it is stored as context

#### Scenario: Signal rejected with feedback

- GIVEN task-001 is at a signal step
- WHEN the SignalPort returns status "rejected" with message "needs timeout handling"
- THEN the outcome is RETRY
- AND the message is stored as a review finding
- AND the finding is composed into the next worker's prompt

#### Scenario: Signal pending

- GIVEN task-001 is at a signal step
- WHEN the SignalPort returns status "pending"
- THEN the outcome is WAIT
- AND the task remains at the current phase

### Requirement: Dependency Ordering

The task processor MUST NOT spawn a worker for a task whose dependencies have not reached "synced" status.

#### Scenario: Dependencies met

- GIVEN task-002 depends on task-001
- WHEN task-001.status is "completed"
- THEN task-002 is eligible for spawning

#### Scenario: Dependencies not met

- GIVEN task-002 depends on task-001
- WHEN task-001.status is "in-progress"
- THEN task-002 remains at "not-started"
- AND no worker is spawned

#### Scenario: Dependency failed

- GIVEN task-002 depends on task-001
- WHEN task-001.status is "failed"
- THEN task-002 cannot proceed
- AND the system reports a deadlock condition

### Requirement: Max Workers

The task processor SHALL limit concurrent workers to a configured maximum.

#### Scenario: Worker limit reached

- GIVEN max_workers is 4 and 4 workers are active
- WHEN 2 additional tasks are eligible for spawning
- THEN no new workers are spawned this cycle
- AND eligible tasks are spawned in subsequent cycles as workers complete

#### Scenario: Deterministic spawn order

- GIVEN 5 eligible tasks and 3 available worker slots
- WHEN the task processor selects which to spawn
- THEN it selects by task ID order (lowest first)
- AND the selection is deterministic

### Requirement: Max Rounds

A task that exceeds the configured maximum rounds SHALL transition to "failed" status.

#### Scenario: Max rounds exceeded

- GIVEN task-001 at round 50 and max_task_rounds is 50
- WHEN the task processor evaluates task-001
- THEN task-001.status transitions to "failed"
- AND the failure reason includes "exceeded max rounds"

### Requirement: Forge-Neutral Step Names

Step names in the phase map SHOULD be forge-neutral abstractions, not platform-specific operations.

#### Scenario: Merge step

- GIVEN a phase runs `action merge`
- WHEN a GitHub adapter is wired
- THEN the adapter performs a GitHub squash-merge
- AND when a GitLab adapter is wired instead, it performs a GitLab MR merge
- AND the phase map is unchanged

### Requirement: PR Lifecycle

The task processor SHALL manage PR creation and draft-to-ready transition as part of the phase map workflow.

#### Scenario: Draft PR created when first needed

- GIVEN task-001 reaches a signal step or action step that requires a PR
- WHEN no PR exists for the task
- THEN a draft PR is created for the task's branch
- AND task-001.pr is set to the PR URL

#### Scenario: Draft-to-ready as explicit phase

- GIVEN a phase map includes a `action mark-ready` phase
- WHEN the task reaches that phase
- THEN the PR transitions from draft to ready for review
- AND this is an explicit, deliberate step — not automatic

### Requirement: First-Phase Initialization

When a task transitions from "not-started" to "in-progress", the task processor SHALL set its phase to the first phase in the phase map.

#### Scenario: Task pickup

- GIVEN task-001 has status "not-started" and phase null
- WHEN the task processor spawns its first worker
- THEN task-001.status becomes "in-progress"
- AND task-001.phase becomes the first phase in the phase map (e.g., "implement")
