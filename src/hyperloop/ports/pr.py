"""PRManager port — interface for PR lifecycle operations.

Implementations: PRManager (gh CLI), FakePRManager (in-memory for tests).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PRState:
    """Snapshot of a PR's current state on GitHub.

    state: "OPEN", "CLOSED", or "MERGED".
    head_sha: the branch tip SHA. For MERGED PRs, this is the branch commit
              that was incorporated — compare with the current branch tip to
              detect unmerged work pushed after the merge.
    """

    state: str
    head_sha: str


class PRPort(Protocol):
    """Interface for PR lifecycle: gate polling, rebase, and merge."""

    def get_pr_state(self, pr_url: str) -> PRState | None:
        """Return the PR's current state, or None if not found."""
        ...

    def create_draft(
        self,
        task_id: str,
        branch: str,
        title: str,
        spec_ref: str,
        pr_title: str | None = None,
        pr_description: str | None = None,
    ) -> str:
        """Create a draft PR. Returns PR URL. Adds spec/task labels."""
        ...

    def check_gate(self, pr_url: str, gate: str) -> bool:
        """Check if a gate signal is present. Returns True if gate is cleared."""
        ...

    def mark_ready(self, pr_url: str) -> None:
        """Mark a draft PR as ready for review."""
        ...

    def wait_mergeable(self, pr_url: str, timeout_s: float = 30.0) -> bool:
        """Poll until the PR is mergeable. Returns False on timeout/conflict."""
        ...

    def merge(self, pr_url: str, task_id: str, spec_ref: str) -> bool:
        """Squash-merge a PR. Returns True on success, False on conflict."""
        ...

    def rebase_branch(self, branch: str, base_branch: str) -> bool:
        """Rebase a branch onto base. Returns True if clean, False if conflicts."""
        ...

    def remove_gate_label(self, pr_url: str) -> None:
        """Remove the gate label after successful merge."""
        ...

    def add_label(self, pr_url: str, label: str) -> None:
        """Add a label to a PR."""
        ...

    def remove_label(self, pr_url: str, label: str) -> None:
        """Remove a label from a PR."""
        ...

    def get_feedback(self, pr_url: str) -> str:
        """Collect PR feedback: CI check results and review comments.

        Returns a formatted string suitable for injection into an agent's
        prompt. Returns empty string if no feedback is available.
        """
        ...
