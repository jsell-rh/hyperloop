"""FeedbackPort — interface for tracking processed PR comments via emoji reactions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from hyperloop.domain.model import PRComment, Task


class FeedbackPort(Protocol):
    """Port for fetching and marking PR comments as processed."""

    def get_unprocessed(
        self, task: Task, allowed_authors: list[str], processed_emoji: str
    ) -> list[PRComment]:
        """Return PR comments from allowed_authors without processed_emoji reaction."""
        ...

    def mark_processed(self, task: Task, comment_ids: list[str], emoji: str) -> None:
        """Add emoji reaction to comments to mark them as seen."""
        ...
