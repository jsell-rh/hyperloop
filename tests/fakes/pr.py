"""FakePRManager — complete in-memory implementation of the PRManager interface.

A first-class fake, tested via contract tests, reusable across all tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class _PRRecord:
    """Internal representation of a PR in the fake."""

    task_id: str
    branch: str
    title: str
    spec_ref: str
    labels: set[str]
    draft: bool
    merged: bool


class FakePRManager:
    """In-memory implementation of the PRManager interface.

    Stores PR state in dictionaries. No subprocess calls, no gh CLI.
    Provides configuration helpers for tests to set up pass/fail scenarios.
    """

    def __init__(
        self,
        repo: str,
        merge_strategy: str = "squash",
        delete_branch: bool = True,
    ) -> None:
        self.repo = repo
        self.merge_strategy = merge_strategy
        self.delete_branch = delete_branch

        self._prs: dict[str, _PRRecord] = {}
        self._pr_counter: int = 0
        self._merge_fails: set[str] = set()
        self._rebase_fails: set[str] = set()

        # Recording for assertions
        self.marked_ready: list[str] = []
        self.merged: list[str] = []
        self.rebased: list[tuple[str, str]] = []

    # -- Configuration helpers (for tests) ------------------------------------

    def set_merge_fails(self, pr_url: str) -> None:
        """Pre-configure merge() to return False for this PR URL."""
        self._merge_fails.add(pr_url)

    def set_rebase_fails(self, branch: str) -> None:
        """Pre-configure rebase_branch() to return False for this branch."""
        self._rebase_fails.add(branch)

    def add_label(self, pr_url: str, label: str) -> None:
        """Add a label to a PR (simulates external human action)."""
        self._prs[pr_url].labels.add(label)

    def get_labels(self, pr_url: str) -> set[str]:
        """Return the current labels on a PR (test helper)."""
        return set(self._prs[pr_url].labels)

    def is_draft(self, pr_url: str) -> bool:
        """Check if a PR is still in draft state (test helper)."""
        return self._prs[pr_url].draft

    def get_pr_info(self, pr_url: str) -> dict[str, str]:
        """Return basic PR info (test helper)."""
        rec = self._prs[pr_url]
        return {
            "branch": rec.branch,
            "title": rec.title,
            "spec_ref": rec.spec_ref,
            "task_id": rec.task_id,
        }

    # -- PRManager interface ---------------------------------------------------

    def create_draft(self, task_id: str, branch: str, title: str, spec_ref: str) -> str:
        """Create a draft PR. Returns PR URL. Adds spec/task labels."""
        self._pr_counter += 1
        url = f"https://github.com/{self.repo}/pull/{self._pr_counter}"

        # Derive spec label: "specs/persistence.md" -> "spec/persistence"
        spec_name = _spec_name_from_ref(spec_ref)

        labels = {f"task/{task_id}", f"spec/{spec_name}"}

        self._prs[url] = _PRRecord(
            task_id=task_id,
            branch=branch,
            title=title,
            spec_ref=spec_ref,
            labels=labels,
            draft=True,
            merged=False,
        )
        return url

    def check_gate(self, pr_url: str, gate: str) -> bool:
        """Check if a gate signal is present. v1: checks for 'lgtm' label."""
        rec = self._prs[pr_url]
        return "lgtm" in rec.labels

    def remove_gate_label(self, pr_url: str) -> None:
        """Remove the lgtm label after successful merge."""
        rec = self._prs.get(pr_url)
        if rec is not None:
            rec.labels.discard("lgtm")

    def mark_ready(self, pr_url: str) -> None:
        """Mark a draft PR as ready for review."""
        self._prs[pr_url].draft = False
        self.marked_ready.append(pr_url)

    def merge(self, pr_url: str, task_id: str, spec_ref: str) -> bool:
        """Squash-merge a PR, preserving trailers. Returns True on success.

        If merge conflict (pre-configured via set_merge_fails), returns False.
        """
        if pr_url in self._merge_fails:
            return False
        self._prs[pr_url].merged = True
        self.merged.append(pr_url)
        return True

    def rebase_branch(self, branch: str, base_branch: str) -> bool:
        """Rebase a branch onto base. Returns True if clean, False if conflicts."""
        self.rebased.append((branch, base_branch))
        return branch not in self._rebase_fails


def _spec_name_from_ref(spec_ref: str) -> str:
    """Derive a spec label name from a spec_ref path.

    'specs/persistence.md' -> 'persistence'
    'specs/sub/feature.md' -> 'sub/feature'
    """
    # Remove 'specs/' prefix and '.md' suffix
    name = spec_ref
    name = re.sub(r"^specs/", "", name)
    name = re.sub(r"\.md$", "", name)
    return name
