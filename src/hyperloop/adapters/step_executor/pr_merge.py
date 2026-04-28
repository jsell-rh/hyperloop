"""PRMergeStep -- squash-merge a task's PR via the PRPort.

Returns StepResult with ADVANCE/RETRY/WAIT outcomes.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from hyperloop.domain.model import StepOutcome, StepResult

if TYPE_CHECKING:
    from hyperloop.domain.model import Task
    from hyperloop.ports.pr import PRPort


class PRMergeStep:
    """StepExecutor handler for merge-pr. Waits for mergeable, squash-merges."""

    def __init__(
        self,
        pr: PRPort,
        base_branch: str = "main",
        repo_path: str | None = None,
    ) -> None:
        self._pr = pr
        self._base_branch = base_branch
        self._repo_path = repo_path

    def execute(self, task: Task, step_name: str, args: dict[str, object]) -> StepResult:
        """Execute the merge-pr step for a task.

        Returns:
            ADVANCE -- PR merged
            WAIT -- transient failure (PR not ready, temporarily not mergeable)
            RETRY -- persistent failure (PR not mergeable, merge conflict)
        """
        branch = task.branch
        if branch is None:
            return StepResult(outcome=StepOutcome.RETRY, detail="Task has no branch")

        pr_url = task.pr
        new_pr_url: str | None = None

        # If no PR exists, create one
        if pr_url is None:
            pr_url = self._pr.create_draft(
                task.id,
                branch,
                task.title,
                task.spec_ref,
                pr_title=task.pr_title,
                pr_description=task.pr_description,
            )
            if not pr_url:
                return StepResult(outcome=StepOutcome.WAIT, detail="Failed to create PR")
            new_pr_url = pr_url

        # Check PR state
        pr_state = self._pr.get_pr_state(pr_url)
        if pr_state is None:
            return StepResult(outcome=StepOutcome.WAIT, detail="PR not found")

        if pr_state.state == "MERGED":
            branch_tip = self._get_branch_tip(branch)
            if branch_tip is None or pr_state.head_sha == branch_tip:
                return StepResult(outcome=StepOutcome.ADVANCE, detail="Already merged")
            pr_url = self._pr.create_draft(
                task.id,
                branch,
                task.title,
                task.spec_ref,
                pr_title=task.pr_title,
                pr_description=task.pr_description,
            )
            if not pr_url:
                return StepResult(
                    outcome=StepOutcome.WAIT,
                    detail="Failed to recreate PR after stale merge",
                )
            new_pr_url = pr_url

        elif pr_state.state == "CLOSED":
            pr_url = self._pr.create_draft(
                task.id,
                branch,
                task.title,
                task.spec_ref,
                pr_title=task.pr_title,
                pr_description=task.pr_description,
            )
            if not pr_url:
                return StepResult(
                    outcome=StepOutcome.WAIT,
                    detail="Failed to recreate closed PR",
                )
            new_pr_url = pr_url

        # Wait for mergeable — attempt auto-rebase on conflict
        if not self._pr.wait_mergeable(pr_url):
            if not self._pr.rebase_branch(branch, self._base_branch):
                return StepResult(
                    outcome=StepOutcome.RETRY,
                    detail="PR not mergeable -- rebase failed (code conflicts with "
                    + self._base_branch
                    + ")",
                )
            if not self._pr.wait_mergeable(pr_url):
                return StepResult(
                    outcome=StepOutcome.RETRY,
                    detail="PR not mergeable after rebase -- " + self._base_branch,
                )

        # Merge
        if not self._pr.merge(pr_url, task.id, task.spec_ref):
            return StepResult(outcome=StepOutcome.RETRY, detail="Merge failed")

        # Cleanup
        self._pr.remove_gate_label(pr_url)

        return StepResult(
            outcome=StepOutcome.ADVANCE,
            detail="Merged",
            pr_url=new_pr_url,
        )

    def _get_branch_tip(self, branch: str) -> str | None:
        """Return the SHA of a remote branch tip, or None."""
        git_cmd = ["git"]
        if self._repo_path is not None:
            git_cmd = ["git", "-C", self._repo_path]
        subprocess.run(
            [*git_cmd, "fetch", "origin", branch],
            capture_output=True,
            text=True,
        )
        result = subprocess.run(
            [*git_cmd, "rev-parse", f"origin/{branch}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
