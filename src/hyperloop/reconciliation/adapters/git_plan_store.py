from __future__ import annotations

import subprocess
from pathlib import Path

from hyperloop.reconciliation.models.plan import Plan

PLAN_BRANCH = "hyperloop/plan"
PLAN_FILE = "plan.json"


class GitPlanStore:
    def __init__(self, repo_path: Path, *, remote: str = "origin") -> None:
        self._repo_path = repo_path
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
            parent = self._git("rev-parse", PLAN_BRANCH).stdout.strip()
            self._create_plan_commit(plan, parent=parent)
        self._push_plan_branch()

    def _read_plan(self) -> Plan:
        result = self._git("show", f"{PLAN_BRANCH}:{PLAN_FILE}")
        return Plan.model_validate_json(result.stdout)

    def _create_plan_commit(self, plan: Plan, *, parent: str | None) -> None:
        json_content = plan.model_dump_json(indent=2)

        blob_sha = self._git(
            "hash-object", "-w", "--stdin", input=json_content
        ).stdout.strip()

        tree_entry = f"100644 blob {blob_sha}\t{PLAN_FILE}"
        tree_sha = self._git("mktree", input=tree_entry).stdout.strip()

        commit_args = ["commit-tree", tree_sha, "-m", "Update plan"]
        if parent is not None:
            commit_args.extend(["-p", parent])
        commit_sha = self._git(*commit_args).stdout.strip()

        self._git("update-ref", f"refs/heads/{PLAN_BRANCH}", commit_sha)

    def _branch_exists(self) -> bool:
        result = self._git(
            "rev-parse", "--verify", f"refs/heads/{PLAN_BRANCH}", check=False
        )
        return result.returncode == 0

    def _fetch_plan_branch(self) -> None:
        self._git("fetch", self._remote, f"{PLAN_BRANCH}:{PLAN_BRANCH}", check=False)

    def _push_plan_branch(self) -> None:
        self._git("push", self._remote, PLAN_BRANCH)

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
            input=input,
            check=check,
        )
