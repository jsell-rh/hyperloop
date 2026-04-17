"""PRManager port — interface for PR lifecycle operations.

Implementations: PRManager (gh CLI), FakePRManager (in-memory for tests).
"""

from __future__ import annotations

from typing import Protocol


class PRPort(Protocol):
    """Interface for PR lifecycle: gate polling, rebase, and merge."""

    def create_draft(self, task_id: str, branch: str, title: str, spec_ref: str) -> str:
        """Create a draft PR. Returns PR URL. Adds spec/task labels."""
        ...

    def check_gate(self, pr_url: str, gate: str) -> bool:
        """Check if a gate signal is present. Returns True if gate is cleared."""
        ...

    def mark_ready(self, pr_url: str) -> None:
        """Mark a draft PR as ready for review."""
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
