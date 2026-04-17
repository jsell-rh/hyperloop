"""PR manager — draft PR lifecycle: creation, labeling, gate polling, merge.

Uses the `gh` CLI for all GitHub operations. The interface is matched by
FakePRManager (tests/fakes/pr.py) for testing without a real GitHub repo.
"""

from __future__ import annotations

import json
import re
import subprocess

import structlog

from hyperloop.ports.pr import PRState

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


class PRManager:
    """Manages draft PR lifecycle: creation, labeling, gate polling, merge."""

    def __init__(
        self,
        repo: str,
        merge_strategy: str = "squash",
        delete_branch: bool = True,
        has_gate: bool = False,
    ) -> None:
        self.repo = repo
        self.merge_strategy = merge_strategy
        self.delete_branch = delete_branch
        self._has_gate = has_gate
        self._ensured_labels: set[str] = set()

    def _ensure_label(self, name: str, color: str = "C5DEF5") -> None:
        """Create a label on the repo if it doesn't exist. Idempotent."""
        if name in self._ensured_labels:
            return
        subprocess.run(
            [
                "gh",
                "label",
                "create",
                name,
                "--color",
                color,
                "--repo",
                self.repo,
            ],
            capture_output=True,
            text=True,
        )
        self._ensured_labels.add(name)

    def ensure_gate_labels(self) -> None:
        """Create gate labels (e.g. lgtm) on the repo. Call at startup."""
        self._ensure_label("lgtm", "0E8A16")
        self._ensure_label("hyperloop", "1D76DB")

    def get_pr_state(self, pr_url: str) -> PRState | None:
        """Return the PR's current state, or None if not found."""
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                pr_url,
                "--json",
                "state,headRefOid",
                "--repo",
                self.repo,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        state = str(data.get("state", ""))
        head_sha = str(data.get("headRefOid", ""))
        if not state:
            return None
        return PRState(state=state, head_sha=head_sha)

    def create_draft(self, task_id: str, branch: str, title: str, spec_ref: str) -> str:
        """Create a draft PR. Returns PR URL. Adds spec/task labels.

        If the branch already has a PR, returns the existing PR URL.
        Label failures are logged and swallowed (labels may not exist on the repo).
        """
        # Check if an open PR already exists for this branch
        existing = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                branch,
                "--json",
                "url,state",
                "--repo",
                self.repo,
            ],
            capture_output=True,
            text=True,
        )
        if existing.returncode == 0:
            data = json.loads(existing.stdout)
            state = str(data.get("state", ""))
            pr_url = str(data.get("url", ""))
            if pr_url and state == "OPEN":
                logger.info("PR already exists for %s: %s", branch, pr_url)
                return pr_url

        # Push the branch first (gh pr create needs it on the remote)
        subprocess.run(
            ["git", "push", "-u", "origin", branch],
            capture_output=True,
            text=True,
        )

        body = _pr_body(task_id, spec_ref, self._has_gate)
        result = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--draft",
                "--head",
                branch,
                "--title",
                title,
                "--body",
                body,
                "--repo",
                self.repo,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning("Failed to create draft PR for %s: %s", task_id, result.stderr.strip())
            return ""

        pr_url = result.stdout.strip()

        # Ensure labels exist, then add them
        spec_name = _spec_name_from_ref(spec_ref)
        task_label = f"hyperloop/task/{task_id}"
        spec_label = f"hyperloop/spec/{spec_name}"
        self._ensure_label("hyperloop", "1D76DB")
        self._ensure_label(task_label, "C5DEF5")
        self._ensure_label(spec_label, "D4C5F9")

        label_result = subprocess.run(
            [
                "gh",
                "pr",
                "edit",
                pr_url,
                "--add-label",
                f"hyperloop,{task_label},{spec_label}",
                "--repo",
                self.repo,
            ],
            capture_output=True,
            text=True,
        )
        if label_result.returncode != 0:
            logger.warning("Failed to add labels to PR %s: %s", pr_url, label_result.stderr.strip())

        logger.info("Created draft PR %s for task %s", pr_url, task_id)
        return pr_url

    def check_gate(self, pr_url: str, gate: str) -> bool:
        """Check if a gate signal is present. v1: checks for 'lgtm' label.

        Returns True if gate is cleared. Does NOT remove the label — that
        happens after successful merge to avoid losing the signal on merge failure.
        """
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                pr_url,
                "--json",
                "labels",
                "--repo",
                self.repo,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False

        data = json.loads(result.stdout)
        label_names = {label["name"] for label in data.get("labels", [])}

        if "lgtm" in label_names:
            logger.info("Gate '%s' cleared for PR %s (lgtm label found)", gate, pr_url)
            return True

        return False

    def remove_gate_label(self, pr_url: str) -> None:
        """Remove the lgtm label after successful merge."""
        subprocess.run(
            [
                "gh",
                "pr",
                "edit",
                pr_url,
                "--remove-label",
                "lgtm",
                "--repo",
                self.repo,
            ],
            capture_output=True,
            text=True,
        )

    def mark_ready(self, pr_url: str) -> None:
        """Mark a draft PR as ready for review. Best-effort — logs on failure."""
        result = subprocess.run(
            [
                "gh",
                "pr",
                "ready",
                pr_url,
                "--repo",
                self.repo,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning("Failed to mark PR %s as ready: %s", pr_url, result.stderr.strip())
            return
        logger.info("Marked PR %s as ready for review", pr_url)

    def wait_mergeable(self, pr_url: str, timeout_s: float = 30.0) -> bool:
        """Poll until the PR is mergeable. Returns False on timeout/conflict.

        After a force-push (rebase), GitHub recalculates mergeability
        asynchronously. The ``mergeable`` field is ``UNKNOWN`` during this
        window. Attempting to merge while UNKNOWN fails with
        "Pull Request is not mergeable".
        """
        import time

        deadline = time.monotonic() + timeout_s
        interval = 2.0
        while time.monotonic() < deadline:
            result = subprocess.run(
                [
                    "gh",
                    "pr",
                    "view",
                    pr_url,
                    "--json",
                    "mergeable",
                    "--repo",
                    self.repo,
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return False

            data = json.loads(result.stdout)
            status = str(data.get("mergeable", ""))
            if status == "MERGEABLE":
                return True
            if status == "CONFLICTING":
                return False
            # UNKNOWN — GitHub is still calculating, poll again
            time.sleep(interval)

        logger.warning("PR %s still UNKNOWN after %.0fs, proceeding anyway", pr_url, timeout_s)
        return True  # Optimistic: let merge() handle the actual failure

    def merge(self, pr_url: str, task_id: str, spec_ref: str) -> bool:
        """Squash-merge a PR, preserving trailers. Returns True on success.

        If merge conflict, returns False (caller handles NEEDS_REBASE).
        """
        delete_flag = "--delete-branch" if self.delete_branch else ""
        body = f"Spec-Ref: {spec_ref}\nTask-Ref: {task_id}"

        cmd = [
            "gh",
            "pr",
            "merge",
            pr_url,
            f"--{self.merge_strategy}",
            "--body",
            body,
            "--repo",
            self.repo,
        ]
        if delete_flag:
            cmd.append(delete_flag)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.warning("Merge failed for PR %s: %s", pr_url, result.stderr.strip())
            return False

        logger.info("Merged PR %s for task %s", pr_url, task_id)
        return True

    def rebase_branch(self, branch: str, base_branch: str) -> bool:
        """Rebase a branch onto base. Returns True if clean, False if conflicts.

        Uses a temporary worktree to avoid checking out the branch in the
        main repo (which would conflict with uncommitted state changes and
        leave the repo on the wrong branch).
        """
        import tempfile

        with tempfile.TemporaryDirectory(prefix="hyperloop-rebase-") as tmpdir:
            # Create a temporary worktree for the branch
            wt = subprocess.run(
                ["git", "worktree", "add", tmpdir, branch],
                capture_output=True,
                text=True,
            )
            if wt.returncode != 0:
                logger.warning("Failed to create worktree for %s: %s", branch, wt.stderr.strip())
                return False

            try:
                # Fetch latest base
                subprocess.run(
                    ["git", "-C", tmpdir, "fetch", "origin", base_branch],
                    capture_output=True,
                    text=True,
                )

                # Rebase onto base — auto-resolve state file conflicts
                rebase = subprocess.run(
                    ["git", "-C", tmpdir, "rebase", f"origin/{base_branch}"],
                    capture_output=True,
                    text=True,
                )
                if rebase.returncode != 0 and not _resolve_rebase_state_conflicts(tmpdir):
                    subprocess.run(
                        ["git", "-C", tmpdir, "rebase", "--abort"],
                        capture_output=True,
                        text=True,
                    )
                    logger.warning("Rebase conflict on branch %s onto %s", branch, base_branch)
                    return False

                # Push the rebased branch
                push = subprocess.run(
                    ["git", "-C", tmpdir, "push", "--force-with-lease", "origin", branch],
                    capture_output=True,
                    text=True,
                )
                if push.returncode != 0:
                    # force-with-lease can fail if tracking ref is stale — retry with --force
                    push = subprocess.run(
                        ["git", "-C", tmpdir, "push", "--force", "origin", branch],
                        capture_output=True,
                        text=True,
                    )
                    if push.returncode != 0:
                        logger.warning(
                            "Push failed after rebase of %s: %s",
                            branch,
                            push.stderr.strip(),
                        )
                        return False

                logger.info("Rebased branch %s onto %s", branch, base_branch)
                return True
            finally:
                # Clean up the worktree
                subprocess.run(
                    ["git", "worktree", "remove", "--force", tmpdir],
                    capture_output=True,
                    text=True,
                )


def _pr_body(task_id: str, spec_ref: str, has_gate: bool) -> str:
    """Generate the PR description body."""
    lines = [
        f"**Task:** `{task_id}`",
        f"**Spec:** `{spec_ref}`",
        "",
        "---",
        "",
        "This PR was created by [hyperloop](https://github.com/jsell-rh/hyperloop),",
        "an AI agent orchestrator.",
        "",
    ]

    if has_gate:
        lines.extend(
            [
                "### Approval",
                "",
                "This PR requires human approval before merge.",
                "Add the **`lgtm`** label to approve.",
                "",
            ]
        )

    lines.extend(
        [
            "### Merge",
            "",
            "The orchestrator will squash-merge this PR automatically",
            "once all pipeline steps pass"
            + (" and the `lgtm` label is applied" if has_gate else "")
            + ".",
        ]
    )

    return "\n".join(lines)


def _resolve_rebase_state_conflicts(tmpdir: str) -> bool:
    """Auto-resolve .hyperloop/state/ conflicts during rebase, then continue.

    State file ownership:
      - tasks/   → take ours (main/trunk, the rebase target)
      - reviews/ → take theirs (worker commit being replayed)

    If non-state conflicts exist, returns False (caller should abort).
    May loop through multiple conflicting commits (rebase --continue
    can hit the next conflict).
    """
    max_rounds = 20  # Safety limit — a rebase shouldn't have 20+ conflicts
    for _ in range(max_rounds):
        # Get list of unmerged (conflicting) files
        result = subprocess.run(
            ["git", "-C", tmpdir, "diff", "--name-only", "--diff-filter=U"],
            capture_output=True,
            text=True,
        )
        conflicted = [f for f in result.stdout.strip().splitlines() if f]
        if not conflicted:
            return True  # No more conflicts — rebase is done

        # Check if ALL conflicts are in .hyperloop/state/
        non_state = [f for f in conflicted if not f.startswith(".hyperloop/state/")]
        if non_state:
            return False  # Real conflicts — caller should abort

        # Resolve state files
        for f in conflicted:
            if f.startswith(".hyperloop/state/tasks/"):
                # Orchestrator owns task files — take trunk version
                subprocess.run(
                    ["git", "-C", tmpdir, "checkout", "--ours", "--", f],
                    capture_output=True,
                )
            else:
                # Worker owns review files — take worker version
                subprocess.run(
                    ["git", "-C", tmpdir, "checkout", "--theirs", "--", f],
                    capture_output=True,
                )
            subprocess.run(
                ["git", "-C", tmpdir, "add", f],
                capture_output=True,
            )

        # Continue the rebase — may hit another conflict on the next commit
        cont = subprocess.run(
            ["git", "-C", tmpdir, "rebase", "--continue"],
            capture_output=True,
            text=True,
            env={**subprocess.os.environ, "GIT_EDITOR": "true"},
        )
        if cont.returncode == 0:
            return True  # Rebase completed successfully

    return False  # Exceeded max rounds


def _spec_name_from_ref(spec_ref: str) -> str:
    """Derive a spec label name from a spec_ref path.

    'specs/persistence.md' -> 'persistence'
    'specs/sub/feature.md' -> 'sub/feature'
    """
    name = spec_ref
    name = re.sub(r"^specs/", "", name)
    name = re.sub(r"\.md$", "", name)
    return name
