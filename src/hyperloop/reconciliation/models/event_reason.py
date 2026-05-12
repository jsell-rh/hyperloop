from __future__ import annotations

from enum import StrEnum


class EventReason(StrEnum):
    RECONCILER_STARTED = "ReconcilerStarted"
    TASK_COMPLETED = "TaskCompleted"
    TASK_FAILED = "TaskFailed"
    MERGE_CONFLICT = "MergeConflict"
    VERIFICATION_FAILED = "VerificationFailed"
    VERIFICATION_PASSED = "VerificationPassed"
    SPEC_SYNCED = "SpecSynced"
    INTEGRATION_FAILED = "IntegrationFailed"
    TASK_RETRIED = "TaskRetried"
    DEPENDENCY_INVALIDATED = "DependencyInvalidated"
