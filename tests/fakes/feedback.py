"""FakeFeedbackPort — in-memory implementation of the FeedbackPort.

A first-class fake, tested via contract tests, reusable across all tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperloop.domain.model import PRComment, Task


class FakeFeedbackPort:
    """In-memory FeedbackPort that tracks comments and processed state."""

    def __init__(self) -> None:
        self._comments: dict[str, list[PRComment]] = {}
        self._processed: set[str] = set()
        self.get_unprocessed_calls: list[tuple[str, list[str], str]] = []
        self.mark_processed_calls: list[tuple[str, list[str], str]] = []

    def add_comment(self, task_id: str, comment: PRComment) -> None:
        """Seed a comment for a given task."""
        self._comments.setdefault(task_id, []).append(comment)

    def get_unprocessed(
        self, task: Task, allowed_authors: list[str], processed_emoji: str
    ) -> list[PRComment]:
        self.get_unprocessed_calls.append((task.id, allowed_authors, processed_emoji))
        comments = self._comments.get(task.id, [])
        return [c for c in comments if c.author in allowed_authors and c.id not in self._processed]

    def mark_processed(self, task: Task, comment_ids: list[str], emoji: str) -> None:
        self.mark_processed_calls.append((task.id, comment_ids, emoji))
        self._processed.update(comment_ids)
