from __future__ import annotations

from enum import StrEnum


class EventReason(StrEnum):
    TASK_FAILED = "TaskFailed"
    VERIFICATION_FAILED = "VerificationFailed"
    VERIFICATION_PASSED = "VerificationPassed"
    DEPENDENCY_INVALIDATED = "DependencyInvalidated"
