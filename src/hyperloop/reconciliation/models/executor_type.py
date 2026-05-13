from __future__ import annotations

from enum import StrEnum


class ExecutorType(StrEnum):
    CLAUDE_SDK = "claude-sdk"
    AMBIENT = "ambient"
