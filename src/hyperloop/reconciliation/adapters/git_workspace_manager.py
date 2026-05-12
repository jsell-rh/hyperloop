from __future__ import annotations

import subprocess
from pathlib import Path

from hyperloop.reconciliation.models.merge_result import MergeOutcome, MergeResult


class GitWorkspaceManager:
    def __init__(
        self,
        repo_path: Path,
        *,
        branch_prefix: str,
        trunk_branch: str,
        remote: str = "origin",
    ) -> None:
        self._repo_path = repo_path
        self._branch_prefix = branch_prefix
        self._trunk_branch = trunk_branch
        self._remote = remote

    def create_delivery_workspace(self, blob_sha: str) -> str:
        branch = self._delivery_branch(blob_sha)
        if not self._branch_exists(branch):
            self._git("branch", branch, self._trunk_branch)
        self._push_branch(branch)
        return f"delivery/{blob_sha}"

    def create_task_workspace(self, blob_sha: str, task_id: int, briefing: str) -> str:
        delivery = self._delivery_branch(blob_sha)
        task = self._task_branch(blob_sha, task_id)
        if not self._branch_exists(task):
            self._git("branch", task, delivery)
            self._create_empty_commit(task, briefing)
        self._push_branch(task)
        return f"task/{blob_sha}/{task_id}"

    def create_verification_workspace(self, blob_sha: str) -> str:
        delivery = self._delivery_branch(blob_sha)
        verifier = self._verifier_branch(blob_sha)
        if self._branch_exists(verifier):
            self._delete_branch(verifier)
        self._git("branch", verifier, delivery)
        self._push_branch(verifier)
        return f"verification/{blob_sha}"

    def merge_task(self, blob_sha: str, task_id: int) -> MergeResult:
        delivery = self._delivery_branch(blob_sha)
        task = self._task_branch(blob_sha, task_id)

        result = self._git("merge-tree", "--write-tree", delivery, task, check=False)

        if result.returncode != 0:
            lines = result.stdout.strip().splitlines()
            conflict_info = "\n".join(lines[1:]) if len(lines) > 1 else ""
            return MergeResult(
                outcome=MergeOutcome.CONFLICT,
                conflict_details=conflict_info or None,
            )

        tree_sha = result.stdout.strip().splitlines()[0]
        delivery_head = self._git("rev-parse", delivery).stdout.strip()
        task_head = self._git("rev-parse", task).stdout.strip()

        merge_commit = self._git(
            "commit-tree",
            tree_sha,
            "-p",
            delivery_head,
            "-p",
            task_head,
            "-m",
            f"Merge task {task_id}",
        ).stdout.strip()

        self._git("update-ref", f"refs/heads/{delivery}", merge_commit)
        self._push_branch(delivery)
        self._delete_branch(task)

        return MergeResult(outcome=MergeOutcome.SUCCESS)

    def integrate(self, blob_sha: str, spec_path: str, title: str, body: str) -> str:
        delivery = self._delivery_branch(blob_sha)
        self._push_branch(delivery)

        result = self._gh(
            "pr",
            "create",
            "--base",
            self._trunk_branch,
            "--head",
            delivery,
            "--title",
            title,
            "--body",
            body,
        )
        return result.stdout.strip()

    def cleanup(self, blob_sha: str) -> None:
        branches = self._list_branches_for_spec(blob_sha)
        for branch in branches:
            self._delete_branch(branch)

    def cleanup_verification(self, blob_sha: str) -> None:
        verifier = self._verifier_branch(blob_sha)
        if self._branch_exists(verifier):
            self._delete_branch(verifier)

    def _delivery_branch(self, blob_sha: str) -> str:
        return f"{self._branch_prefix}spec/{blob_sha}/delivery"

    def _task_branch(self, blob_sha: str, task_id: int) -> str:
        return f"{self._branch_prefix}spec/{blob_sha}/task/{task_id}"

    def _verifier_branch(self, blob_sha: str) -> str:
        return f"{self._branch_prefix}spec/{blob_sha}/verifier"

    def _branch_exists(self, branch: str) -> bool:
        result = self._git("rev-parse", "--verify", f"refs/heads/{branch}", check=False)
        return result.returncode == 0

    def _create_empty_commit(self, branch: str, message: str) -> None:
        tree = self._git("rev-parse", f"{branch}^{{tree}}").stdout.strip()
        parent = self._git("rev-parse", branch).stdout.strip()
        commit = self._git(
            "commit-tree", tree, "-p", parent, "-m", message
        ).stdout.strip()
        self._git("update-ref", f"refs/heads/{branch}", commit)

    def _push_branch(self, branch: str) -> None:
        self._git("push", self._remote, branch, check=False)

    def _delete_branch(self, branch: str) -> None:
        self._git("branch", "-D", branch, check=False)
        self._git("push", self._remote, "--delete", branch, check=False)

    def _list_branches_for_spec(self, blob_sha: str) -> list[str]:
        prefix = f"{self._branch_prefix}spec/{blob_sha}/"
        result = self._git(
            "for-each-ref",
            "--format=%(refname:strip=2)",
            f"refs/heads/{prefix}",
        )
        branches: list[str] = []
        if result.stdout.strip():
            branches.extend(result.stdout.strip().splitlines())
        return branches

    def _git(
        self,
        *args: str,
        input: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self._repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            input=input,
            check=check,
        )

    def _gh(
        self,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["gh", *args],
            cwd=self._repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=check,
        )
