from __future__ import annotations

import json
import subprocess
from enum import StrEnum
from pathlib import Path

from hyperloop.reconciliation.models.integration_poll_result import (
    IntegrationPollResult,
    IntegrationPollStatus,
)
from hyperloop.reconciliation.models.integration_strategy import IntegrationStrategy
from hyperloop.reconciliation.models.merge_result import MergeOutcome, MergeResult
from hyperloop.reconciliation.models.rebase_result import RebaseOutcome, RebaseResult


class _PrState(StrEnum):
    OPEN = "OPEN"
    MERGED = "MERGED"
    CLOSED = "CLOSED"


class _PrMergeable(StrEnum):
    MERGEABLE = "MERGEABLE"
    CONFLICTING = "CONFLICTING"
    UNKNOWN = "UNKNOWN"


class GitWorkspaceManager:
    def __init__(
        self,
        repo_path: Path,
        *,
        branch_prefix: str,
        trunk_branch: str,
        remote: str = "origin",
        integration_strategy: IntegrationStrategy = IntegrationStrategy.PR,
    ) -> None:
        self._repo_path = repo_path
        self._branch_prefix = branch_prefix
        self._trunk_branch = trunk_branch
        self._remote = remote
        self._integration_strategy = integration_strategy

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
            self._git("worktree", "prune", check=False)
            self._delete_branch(verifier)
        if self._branch_exists(verifier):
            delivery_sha = self._git("rev-parse", delivery).stdout.strip()
            self._git("update-ref", f"refs/heads/{verifier}", delivery_sha)
        else:
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

    _MAX_PR_TITLE_LENGTH = 256

    def integrate(self, blob_sha: str, spec_path: str, title: str, body: str) -> str:
        if self._integration_strategy == IntegrationStrategy.DIRECT:
            return self._integrate_direct(blob_sha)
        if self._integration_strategy == IntegrationStrategy.PR_AUTOMERGE:
            return self._integrate_pr_automerge(blob_sha, title, body)
        return self._integrate_pr(blob_sha, title, body)

    def _integrate_pr(self, blob_sha: str, title: str, body: str) -> str:
        delivery = self._delivery_branch(blob_sha)
        self._push_branch(delivery)

        truncated_title = title[: self._MAX_PR_TITLE_LENGTH]

        result = self._gh(
            "pr",
            "create",
            "--base",
            self._trunk_branch,
            "--head",
            delivery,
            "--title",
            truncated_title,
            "--body",
            body,
        )
        return result.stdout.strip()

    def _integrate_pr_automerge(self, blob_sha: str, title: str, body: str) -> str:
        pr_url = self._integrate_pr(blob_sha, title, body)
        self._gh("pr", "merge", pr_url, "--auto", "--merge")
        return pr_url

    def _integrate_direct(self, blob_sha: str) -> str:
        delivery = self._delivery_branch(blob_sha)

        delivery_head = self._git("rev-parse", delivery).stdout.strip()
        trunk_head = self._git("rev-parse", self._trunk_branch).stdout.strip()

        merge_result = self._git(
            "merge-tree", "--write-tree", self._trunk_branch, delivery, check=False
        )

        if merge_result.returncode != 0:
            raise RuntimeError("Direct integration failed: merge conflict")

        tree_sha = merge_result.stdout.strip().splitlines()[0]

        merge_commit = self._git(
            "commit-tree",
            tree_sha,
            "-p",
            trunk_head,
            "-p",
            delivery_head,
            "-m",
            f"Merge {delivery} into {self._trunk_branch}",
        ).stdout.strip()

        self._git("update-ref", f"refs/heads/{self._trunk_branch}", merge_commit)
        self._git("push", self._remote, self._trunk_branch)

        return f"{self._DIRECT_INTEGRATION_PREFIX}{merge_commit}"

    _DIRECT_INTEGRATION_PREFIX = "direct:"

    def poll_integration(self, integration_id: str) -> IntegrationPollResult:
        if integration_id.startswith(self._DIRECT_INTEGRATION_PREFIX):
            return IntegrationPollResult(status=IntegrationPollStatus.MERGED)

        result = self._gh(
            "pr",
            "view",
            integration_id,
            "--json",
            "state,mergeable",
            check=False,
        )

        if result.returncode != 0:
            return IntegrationPollResult(status=IntegrationPollStatus.FAILED)

        data = json.loads(result.stdout)
        state = _PrState(data["state"])
        mergeable = _PrMergeable(data.get("mergeable", _PrMergeable.UNKNOWN))

        if state == _PrState.MERGED:
            return IntegrationPollResult(status=IntegrationPollStatus.MERGED)
        if state == _PrState.CLOSED:
            return IntegrationPollResult(status=IntegrationPollStatus.CLOSED)
        if mergeable == _PrMergeable.CONFLICTING:
            return IntegrationPollResult(
                status=IntegrationPollStatus.CONFLICT,
                conflict_details="Pull request has merge conflicts",
            )
        return IntegrationPollResult(status=IntegrationPollStatus.PENDING)

    def rebase_delivery(self, blob_sha: str) -> RebaseResult:
        delivery = self._delivery_branch(blob_sha)

        self._git("fetch", self._remote, self._trunk_branch)
        trunk_head = self._git(
            "rev-parse", f"{self._remote}/{self._trunk_branch}"
        ).stdout.strip()
        delivery_head = self._git("rev-parse", delivery).stdout.strip()

        merge_base = self._git("merge-base", trunk_head, delivery_head).stdout.strip()

        if merge_base == trunk_head:
            return RebaseResult(outcome=RebaseOutcome.SUCCESS)

        trunk_changes = self._summarize_trunk_changes(merge_base, trunk_head)

        commits = (
            self._git("rev-list", "--reverse", f"{merge_base}..{delivery_head}")
            .stdout.strip()
            .splitlines()
        )

        if not commits:
            self._git("update-ref", f"refs/heads/{delivery}", trunk_head)
            self._force_push_branch(delivery)
            return RebaseResult(
                outcome=RebaseOutcome.SUCCESS, trunk_changes=trunk_changes
            )

        current_parent = trunk_head
        for commit_sha in commits:
            original_parent = self._git("rev-parse", f"{commit_sha}^").stdout.strip()

            merge_result = self._git(
                "merge-tree",
                "--write-tree",
                f"--merge-base={original_parent}",
                current_parent,
                commit_sha,
                check=False,
            )

            if merge_result.returncode != 0:
                lines = merge_result.stdout.strip().splitlines()
                conflict_info = "\n".join(lines[1:]) if len(lines) > 1 else None
                return RebaseResult(
                    outcome=RebaseOutcome.CONFLICT,
                    conflict_details=conflict_info,
                )

            tree_sha = merge_result.stdout.strip().splitlines()[0]
            message = self._git("log", "-1", "--format=%B", commit_sha).stdout.strip()

            new_commit = self._git(
                "commit-tree",
                tree_sha,
                "-p",
                current_parent,
                "-m",
                message,
            ).stdout.strip()

            current_parent = new_commit

        self._git("update-ref", f"refs/heads/{delivery}", current_parent)
        self._force_push_branch(delivery)
        return RebaseResult(outcome=RebaseOutcome.SUCCESS, trunk_changes=trunk_changes)

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

    def _force_push_branch(self, branch: str) -> None:
        self._git("push", "--force", self._remote, branch, check=False)

    def _delete_branch(self, branch: str) -> None:
        self._git("branch", "-D", branch, check=False)
        self._git("push", self._remote, "--delete", branch, check=False)

    def _summarize_trunk_changes(self, merge_base: str, trunk_head: str) -> str:
        log = self._git(
            "log",
            "--oneline",
            f"{merge_base}..{trunk_head}",
        ).stdout.strip()
        stat = self._git(
            "diff",
            "--stat",
            merge_base,
            trunk_head,
        ).stdout.strip()
        return f"{log}\n\n{stat}"

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
        result = subprocess.run(
            ["gh", *args],
            cwd=self._repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if check and result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            cmd_preview = " ".join(args[:2])
            raise RuntimeError(
                f"gh {cmd_preview} failed (exit {result.returncode}): {detail}"
            )
        return result
