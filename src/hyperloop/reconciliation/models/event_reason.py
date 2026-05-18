from __future__ import annotations

from enum import StrEnum


class EventReason(StrEnum):
    RECONCILER_STARTED = "ReconcilerStarted"
    DECOMPOSITION_COMPLETED = "DecompositionCompleted"
    DECOMPOSITION_FAILED = "DecompositionFailed"
    TASK_DISPATCHED = "TaskDispatched"
    TASK_COMPLETED = "TaskCompleted"
    TASK_FAILED = "TaskFailed"
    MERGE_CONFLICT = "MergeConflict"
    VERIFICATION_FAILED = "VerificationFailed"
    VERIFICATION_PASSED = "VerificationPassed"
    SPEC_SYNCED = "SpecSynced"
    INTEGRATION_SUBMITTED = "IntegrationSubmitted"
    INTEGRATION_FAILED = "IntegrationFailed"
    INTEGRATION_MERGED = "IntegrationMerged"
    DELIVERY_REBASED = "DeliveryRebased"
    REBASE_FAILED = "RebaseFailed"
    PR_CLOSED = "PRClosed"
    DEPENDENCY_INVALIDATED = "DependencyInvalidated"
    VERIFICATION_AGENT_CRASHED = "VerificationAgentCrashed"
