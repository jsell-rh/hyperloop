# Reconciliation State Machine Specification

## Purpose

Defines the lifecycle states of a spec within the reconciliation engine and the rules governing transitions between them. A spec progresses through states as the system detects divergence, performs work, and verifies alignment. The state machine is the authority on whether a spec requires work, is being actively reconciled, or has been verified as aligned.

## Requirements

### Requirement: Spec Reconciliation States

A spec's reconciliation status SHALL be one of five states:

| State | Meaning |
|---|---|
| OutOfSync | The spec's current content-addressable version has no verified implementation |
| Reconciling | Decomposition has been performed and work is in progress (or vacuously complete) |
| Verifying | All tasks are complete; a verification agent is assessing alignment |
| PendingIntegration | Verification passed, integration submitted, awaiting confirmation that code reached trunk |
| Synced | The verified implementation has been integrated to trunk |
| Failed | The system has exhausted its ability to reconcile; human intervention is required |

#### Scenario: New spec enters OutOfSync

- GIVEN a spec file is committed to the repository
- WHEN the reconciler detects the spec for the first time
- THEN the spec's status SHALL be OutOfSync

#### Scenario: Modified spec enters OutOfSync

- GIVEN a spec with status Synced at blob SHA abc123
- WHEN the spec is modified, producing blob SHA def456
- THEN the spec's status at def456 SHALL be OutOfSync

### Requirement: State Transitions

The system SHALL enforce the following state transitions. No other transitions are valid.

| From | To | Trigger |
|---|---|---|
| OutOfSync | Reconciling | Decomposition completes for this spec (regardless of task count) |
| Reconciling | Verifying | All tasks for this spec reach Complete status |
| Verifying | PendingIntegration | Verification agent confirms alignment and integration is submitted |
| Verifying | OutOfSync | Verification agent reports misalignment |
| PendingIntegration | Synced | Integration confirmed (PR merged or direct push succeeded) |
| PendingIntegration | Verifying | Trunk merge conflict detected; delivery branch rebased successfully onto trunk |
| PendingIntegration | OutOfSync | Trunk merge conflict detected; rebase failed (conflict too complex for automatic rebase) |
| PendingIntegration | Failed | Integration retry limit exceeded |
| OutOfSync, Reconciling, Verifying | Failed | Convergence bound exceeded |
| Reconciling, Verifying, PendingIntegration, Failed | OutOfSync | Spec is superseded by a new blob SHA |

#### Scenario: OutOfSync to Reconciling

- GIVEN a spec at blob SHA abc123 with status OutOfSync
- WHEN the decomposition agent completes processing this spec
- THEN the spec's status SHALL transition to Reconciling

#### Scenario: Reconciling to Verifying

- GIVEN a spec with status Reconciling
- WHEN all tasks associated with this spec reach Complete status
- THEN the spec's status SHALL transition to Verifying

#### Scenario: Reconciling to Verifying with zero tasks

- GIVEN a spec with status Reconciling and zero tasks (decomposition determined no work is needed)
- WHEN the "all tasks complete" condition is evaluated
- THEN the condition is vacuously true
- AND the spec SHALL transition to Verifying

#### Scenario: Verifying to PendingIntegration

- GIVEN a spec with status Verifying
- WHEN the verification agent confirms the implementation matches the spec
- THEN the spec's status SHALL transition to PendingIntegration
- AND integration SHALL be submitted to trunk via the WorkspaceManager port

#### Scenario: PendingIntegration to Synced

- GIVEN a spec with status PendingIntegration
- WHEN the reconciler polls the integration and confirms it has been merged to trunk
- THEN the spec's status SHALL transition to Synced

#### Scenario: PendingIntegration to Verifying on successful rebase

- GIVEN a spec with status PendingIntegration
- WHEN the reconciler polls the integration and detects a trunk merge conflict
- AND the delivery branch is successfully rebased onto current trunk
- THEN verification SHALL be re-launched with context about the rebase and what changed in trunk
- AND the spec's status SHALL transition to Verifying
- AND this re-verification is targeted — the verifier receives the rebase context and focuses on integration seams

#### Scenario: PendingIntegration to OutOfSync on rebase failure

- GIVEN a spec with status PendingIntegration
- WHEN the reconciler polls the integration and detects a trunk merge conflict
- AND rebasing the delivery branch fails (conflict too complex for automatic rebase)
- THEN the spec's status SHALL transition to OutOfSync
- AND the next decomposition cycle receives the rebase failure context

#### Scenario: PendingIntegration to Failed on retry exhaustion

- GIVEN a spec with status PendingIntegration
- WHEN integration has failed and been retried up to the configured max_integration_retries
- THEN the spec's status SHALL transition to Failed

#### Scenario: Verifying to OutOfSync

- GIVEN a spec with status Verifying
- WHEN the verification agent reports misalignment
- THEN the spec's status SHALL transition to OutOfSync
- AND a VerificationFailed event SHALL be recorded with the verification rationale
- AND the subsequent decomposition SHALL receive this event and produce only targeted corrective tasks

#### Scenario: No direct OutOfSync to Synced

- GIVEN a spec with status OutOfSync
- WHEN any action is taken
- THEN the spec MUST NOT transition directly to Synced
- AND it MUST pass through Reconciling, Verifying, and PendingIntegration

### Requirement: No Self-Grading

Agent sessions MUST NOT assess their own transition criteria. A fresh agent session MUST be used to evaluate the work of another session.

#### Scenario: Verification uses a fresh session

- GIVEN tasks for a spec were completed by implementation agents
- WHEN the system launches verification
- THEN the verification agent SHALL be a fresh session with no shared context from the implementation sessions

#### Scenario: Different model families for verification

- GIVEN the system supports configurable model selection
- WHEN verification is performed
- THEN the system SHOULD use a different model family for verification than was used for implementation

### Requirement: Convergence Bound

The system SHALL enforce a configurable maximum number of reconciliation attempts per spec per blob SHA. When this limit is exceeded, the spec SHALL transition to Failed.

A reconciliation attempt is counted each time a spec cycles from Verifying back to OutOfSync (verification failure), or when all tasks for a spec exhaust their retry and re-decomposition budget. The rebase-triggered re-verification cycle (PendingIntegration → Verifying) is bounded separately by max_integration_retries — each trunk merge conflict that triggers a rebase counts as an integration attempt, and exhausting this limit transitions the spec to Failed.

#### Scenario: Verification retry limit exceeded

- GIVEN a spec at blob SHA abc123 with a configured max verification cycle count
- WHEN the spec has cycled through OutOfSync, Reconciling, Verifying, and back to OutOfSync that many times
- THEN the spec's status SHALL transition to Failed
- AND a human intervention event SHALL be recorded with the accumulated failure context

#### Scenario: Default limit

- GIVEN no explicit convergence bound is configured
- WHEN the system initializes
- THEN a sensible default convergence bound SHALL be used

### Requirement: Superseding

When a spec's blob SHA changes while it is in Reconciling, Verifying, PendingIntegration, or Failed state, the old blob SHA's SpecPlan SHALL be marked as superseded and all in-flight work SHALL be cancelled. Synced SpecPlans are never superseded — a new SpecPlan is created alongside them with status OutOfSync.

#### Scenario: Spec changes during Reconciling

- GIVEN a spec at path "auth.spec.md" with status Reconciling at blob SHA abc123
- WHEN the spec is modified, producing blob SHA def456
- THEN the SpecPlan for abc123 SHALL be marked as superseded
- AND all in-flight agents working on abc123 tasks SHALL be cancelled
- AND a new SpecPlan for def456 SHALL be created with status OutOfSync

#### Scenario: Spec changes during Verifying

- GIVEN a spec with status Verifying at blob SHA abc123
- WHEN the spec is modified, producing blob SHA def456
- THEN the verification agent for abc123 SHALL be cancelled
- AND the SpecPlan for abc123 SHALL be marked as superseded
- AND a new SpecPlan for def456 SHALL be created with status OutOfSync

#### Scenario: Spec changes while Failed

- GIVEN a spec at path "auth.spec.md" with status Failed at blob SHA abc123
- WHEN the spec is modified, producing blob SHA def456
- THEN the SpecPlan for abc123 SHALL be marked as superseded
- AND a new SpecPlan for def456 SHALL be created with status OutOfSync

#### Scenario: Superseded work is discarded

- GIVEN in-flight tasks for superseded blob SHA abc123
- WHEN cancellation is complete
- THEN the results of those tasks SHALL NOT be merged
- AND the tasks SHALL NOT be retried

### Requirement: Deleted Spec Handling

When a spec is deleted from the repository, the system SHALL treat this as superseding by nothing. All in-flight work for the deleted spec SHALL be cancelled and the SpecPlan cleaned up.

#### Scenario: Spec deleted during Reconciling

- GIVEN a spec "old-feature.spec.md" with status Reconciling and tasks in progress
- WHEN the spec file is deleted from the repository
- THEN all in-flight agents for this spec SHALL be cancelled
- AND the SpecPlan SHALL be marked as superseded
- AND no further reconciliation occurs for this spec

#### Scenario: Spec deleted while Synced

- GIVEN a spec "old-feature.spec.md" with status Synced
- WHEN the spec file is deleted from the repository
- THEN the SpecPlan is eligible for cleanup
- AND no immediate action is required

### Requirement: Decomposition Failure

When the decomposition agent itself fails (not the tasks it produces), the system SHALL retry decomposition. Repeated decomposition failures count toward the convergence bound. When the bound is exceeded, the spec SHALL transition to Failed.

#### Scenario: Decomposition agent fails

- GIVEN a spec with status OutOfSync
- WHEN the decomposition agent fails to produce tasks (agent crash, timeout, or invalid output)
- THEN a DecompositionFailed event is recorded
- AND decomposition is retried on the next cycle

#### Scenario: Repeated decomposition failure exceeds convergence bound

- GIVEN a spec whose decomposition agent has failed repeatedly
- WHEN the convergence bound is exceeded
- THEN the spec SHALL transition directly from OutOfSync to Failed
- AND a human intervention event is recorded

### Requirement: Failed is Terminal

The Failed state SHALL be terminal. The only way to re-trigger reconciliation for a failed spec is to modify the spec, producing a new blob SHA. This ensures the human considers whether the spec itself needs clarification before the system retries.

#### Scenario: Failed spec requires spec change to retry

- GIVEN a spec at blob SHA abc123 with status Failed
- WHEN a human wants the system to retry
- THEN they MUST modify the spec (even a trivial edit produces a new blob SHA)
- AND the new blob SHA enters as a fresh OutOfSync SpecPlan
