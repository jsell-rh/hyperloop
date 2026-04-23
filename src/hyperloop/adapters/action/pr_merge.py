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
    """ActionPort adapter for merge-pr. Handles rebase + squash-merge."""

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
            ERROR -- persistent failure (merge conflict after rebase)

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

        # Rebase
        if not self._pr.rebase_branch(branch, self._base_branch):
            conflicts = self._detect_conflicts(branch)
            detail = "Rebase conflict with " + self._base_branch
            if conflicts:
                detail += ". Conflicting files: " + ", ".join(conflicts)
            detail += (
                ". Your work is preserved on the branch. "
                "Please rebase onto " + self._base_branch + " and resolve the conflicts."
            )
            return ActionResult(outcome=ActionOutcome.ERROR, detail=detail)

        # Wait for mergeable
        if not self._pr.wait_mergeable(pr_url):
            return ActionResult(
                outcome=ActionOutcome.ERROR,
                detail="PR not mergeable after rebase",
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

    def _detect_conflicts(self, branch: str) -> list[str]:
        """Detect which files conflict between the branch and base.

        Does a dry-run merge to find conflicting files without modifying
        the working tree.
        """
        import subprocess

        git_cmd = ["git"]
        if self._repo_path is not None:
            git_cmd = ["git", "-C", self._repo_path]

        # Try a merge tree (no-checkout) to detect conflicts
        result = subprocess.run(
            [*git_cmd, "merge-tree", "--write-tree", self._base_branch, branch],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return []

        # Parse conflicting file names from merge-tree output
        conflicts: list[str] = []
        for line in result.stdout.splitlines():
            # merge-tree outputs "CONFLICT (content): ..." lines
            if line.startswith("CONFLICT"):
                # Extract filename — usually last token or after "Merge conflict in "
                if "Merge conflict in " in line:
                    conflicts.append(line.split("Merge conflict in ")[-1].strip())
                elif line.endswith(")"):
                    pass  # Header line like "CONFLICT (content):"
            # Also check informational messages for file paths
            elif line.strip() and not line.startswith(" ") and "/" in line:
                conflicts.append(line.strip())

        return conflicts

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
