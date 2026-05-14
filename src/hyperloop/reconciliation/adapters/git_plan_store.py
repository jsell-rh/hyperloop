from __future__ import annotations

import subprocess
from pathlib import Path

from hyperloop.reconciliation.models.plan import Plan


class GitPlanStore:
    def __init__(
        self,
        repo_path: Path,
        *,
        plan_branch: str,
        plan_file: str,
        remote: str = "origin",
    ) -> None:
        self._repo_path = repo_path
        self._plan_branch = plan_branch
        self._plan_file = plan_file
        self._remote = remote

    def get_plan(self) -> Plan:
        self._fetch_plan_branch()
        if not self._branch_exists():
            empty_plan = Plan()
            self._create_plan_commit(empty_plan, parent=None)
            return empty_plan
        return self._read_plan()

    def write_plan(self, plan: Plan) -> None:
        self._fetch_plan_branch()
        if not self._branch_exists():
            self._create_plan_commit(plan, parent=None)
        else:
            parent = self._git("rev-parse", self._plan_branch).stdout.strip()
            self._create_plan_commit(plan, parent=parent)
        self._push_plan_branch()

    def _read_plan(self) -> Plan:
        result = self._git("show", f"{self._plan_branch}:{self._plan_file}")
        return Plan.model_validate_json(result.stdout)

    def _create_plan_commit(self, plan: Plan, *, parent: str | None) -> None:
        json_content = plan.model_dump_json(indent=2) + "\n"

        blob_sha = self._git(
            "hash-object", "-w", "--stdin", input=json_content
        ).stdout.strip()

        tree_entry = f"100644 blob {blob_sha}\t{self._plan_file}"
        tree_sha = self._git("mktree", input=tree_entry).stdout.strip()

        commit_args = ["commit-tree", tree_sha, "-m", "Update plan"]
        if parent is not None:
            commit_args.extend(["-p", parent])
        commit_sha = self._git(*commit_args).stdout.strip()

        self._git("update-ref", f"refs/heads/{self._plan_branch}", commit_sha)

    def _branch_exists(self) -> bool:
        result = self._git(
            "rev-parse", "--verify", f"refs/heads/{self._plan_branch}", check=False
        )
        return result.returncode == 0

    def _fetch_plan_branch(self) -> None:
        self._git(
            "fetch",
            self._remote,
            f"+refs/heads/{self._plan_branch}:refs/heads/{self._plan_branch}",
            check=False,
        )

    def _push_plan_branch(self) -> None:
        self._git("push", self._remote, self._plan_branch, check=False)

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
