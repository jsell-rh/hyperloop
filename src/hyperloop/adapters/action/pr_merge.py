"""PRMergeAction -- squash-merge a task's PR via the gh CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from hyperloop.ports.action import ActionOutcome, ActionResult

if TYPE_CHECKING:
    from hyperloop.domain.model import Task
    from hyperloop.ports.pr import PRPort

logger = structlog.get_logger()


class PRMergeAction:
    """ActionPort adapter for merge-pr. Waits for mergeable, squash-merges."""

    def __init__(
        self,
        pr: PRPort,
        base_branch: str = "main",
        repo_path: str | None = None,
    ) -> None:
        self._pr = pr
        self._base_branch = base_branch
        self._repo_path = repo_path

    def execute(self, task: Task, action_name: str, args: dict[str, object]) -> ActionResult:
        """Execute the merge-pr action for a task.

        Returns:
            SUCCESS -- PR merged
            RETRY -- transient failure (PR not ready, temporarily not mergeable)
            ERROR -- persistent failure (PR not mergeable, merge conflict)

        If the PR was recreated (was CLOSED), returns the new pr_url in ActionResult.
        """
        if action_name != "merge-pr":
            return ActionResult(
                outcome=ActionOutcome.ERROR,
                detail=f"Unknown action: {action_name}",
            )

        branch = task.branch
        if branch is None:
            return ActionResult(outcome=ActionOutcome.ERROR, detail="Task has no branch")

        pr_url = task.pr
        new_pr_url: str | None = None  # Set if we recreated the PR

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
                return ActionResult(outcome=ActionOutcome.RETRY, detail="Failed to create PR")
            new_pr_url = pr_url

        # Check PR state
        pr_state = self._pr.get_pr_state(pr_url)
        if pr_state is None:
            return ActionResult(outcome=ActionOutcome.RETRY, detail="PR not found")

        if pr_state.state == "MERGED":
            # Verify branch tip matches what was merged
            branch_tip = self._get_branch_tip(branch)
            if branch_tip is None or pr_state.head_sha == branch_tip:
                return ActionResult(outcome=ActionOutcome.SUCCESS, detail="Already merged")
            # Stale merge -- create new PR for remaining work
            pr_url = self._pr.create_draft(
                task.id,
                branch,
                task.title,
                task.spec_ref,
                pr_title=task.pr_title,
                pr_description=task.pr_description,
            )
            if not pr_url:
                return ActionResult(
                    outcome=ActionOutcome.RETRY,
                    detail="Failed to recreate PR after stale merge",
                )
            new_pr_url = pr_url

        elif pr_state.state == "CLOSED":
            # Recreate PR
            pr_url = self._pr.create_draft(
                task.id,
                branch,
                task.title,
                task.spec_ref,
                pr_title=task.pr_title,
                pr_description=task.pr_description,
            )
            if not pr_url:
                return ActionResult(
                    outcome=ActionOutcome.RETRY,
                    detail="Failed to recreate closed PR",
                )
            new_pr_url = pr_url

        # Wait for mergeable
        if not self._pr.wait_mergeable(pr_url):
            return ActionResult(
                outcome=ActionOutcome.ERROR,
                detail="PR not mergeable — may have conflicts with " + self._base_branch,
            )

        # Merge
        if not self._pr.merge(pr_url, task.id, task.spec_ref):
            return ActionResult(outcome=ActionOutcome.ERROR, detail="Merge failed")

        # Cleanup
        self._pr.remove_gate_label(pr_url)

        return ActionResult(
            outcome=ActionOutcome.SUCCESS,
            detail="Merged",
            pr_url=new_pr_url,  # Only set if we recreated
        )

    def _get_branch_tip(self, branch: str) -> str | None:
        """Return the SHA of a remote branch tip, or None."""
        import subprocess

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
