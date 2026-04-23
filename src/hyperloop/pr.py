"""PR manager — draft PR lifecycle: creation, labeling, gate polling, merge.

Uses the `gh` CLI for all GitHub operations. The interface is matched by
FakePRManager (tests/fakes/pr.py) for testing without a real GitHub repo.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import TYPE_CHECKING

from hyperloop.ports.pr import PRState

if TYPE_CHECKING:
    from hyperloop.ports.probe import OrchestratorProbe


class PRManager:
    """Manages draft PR lifecycle: creation, labeling, gate polling, merge."""

    def __init__(
        self,
        repo: str,
        merge_strategy: str = "squash",
        delete_branch: bool = True,
        has_gate: bool = False,
        base_branch: str = "main",
        probe: OrchestratorProbe | None = None,
    ) -> None:
        self.repo = repo
        self.merge_strategy = merge_strategy
        self.delete_branch = delete_branch
        self._has_gate = has_gate
        self._base_branch = base_branch
        self._ensured_labels: set[str] = set()
        self._probe: OrchestratorProbe | None = probe

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
        """Create all hyperloop labels on the repo. Call at startup."""
        self._ensure_label("hyperloop", "1D76DB")
        self._ensure_label("lgtm", "0E8A16")
        self._ensure_label("hyperloop/needs-approval", "FBCA04")

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

    def create_draft(
        self,
        task_id: str,
        branch: str,
        title: str,
        spec_ref: str,
        pr_title: str | None = None,
        pr_description: str | None = None,
    ) -> str:
        """Create a draft PR. Returns PR URL. Adds spec/task labels.

        Uses pr_title if provided (PM-authored), otherwise derives a
        conventional commit-style title from the task title and spec_ref.

        If the branch already has a PR, returns the existing PR URL.
        Label failures are logged and swallowed (labels may not exist on the repo).
        """
        if pr_title is not None:
            title = pr_title
        elif not re.match(r"^(feat|fix|chore|docs|refactor|test|ci|build|perf|style)\b", title):
            title = _conventional_title(title, spec_ref)
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
                return pr_url

        # Push the branch first (gh pr create needs it on the remote)
        subprocess.run(
            ["git", "push", "-u", "origin", branch],
            capture_output=True,
            text=True,
        )

        body = _pr_body(task_id, spec_ref, self._has_gate, pr_description)
        result = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--draft",
                "--head",
                branch,
                "--base",
                self._base_branch,
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
            return ""

        pr_url = result.stdout.strip()

        # Ensure labels exist, then add them
        spec_name = _spec_name_from_ref(spec_ref)
        task_label = f"hyperloop/task/{task_id}"
        spec_label = f"hyperloop/spec/{spec_name}"
        self._ensure_label("hyperloop", "1D76DB")
        self._ensure_label(task_label, "C5DEF5")
        self._ensure_label(spec_label, "D4C5F9")

        subprocess.run(
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
        if self._probe is not None:
            self._probe.pr_created(task_id=task_id, pr_url=pr_url, branch=branch)
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

        return "lgtm" in label_names

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

    def add_label(self, pr_url: str, label: str) -> None:
        """Add a label to a PR. Creates the label on the repo if needed."""
        self._ensure_label(label, "C5DEF5")
        subprocess.run(
            ["gh", "pr", "edit", pr_url, "--add-label", label, "--repo", self.repo],
            capture_output=True,
            text=True,
        )
        if self._probe is not None:
            self._probe.pr_label_changed(pr_url=pr_url, label=label, added=True)

    def remove_label(self, pr_url: str, label: str) -> None:
        """Remove a label from a PR."""
        subprocess.run(
            ["gh", "pr", "edit", pr_url, "--remove-label", label, "--repo", self.repo],
            capture_output=True,
            text=True,
        )
        if self._probe is not None:
            self._probe.pr_label_changed(pr_url=pr_url, label=label, added=False)

    def get_feedback(self, pr_url: str) -> str:
        """Collect PR feedback: CI check results and review comments."""
        sections: list[str] = []

        # CI checks
        checks = subprocess.run(
            ["gh", "pr", "checks", pr_url, "--repo", self.repo],
            capture_output=True,
            text=True,
        )
        if checks.returncode == 0 and checks.stdout.strip():
            sections.append(f"### CI Checks\n```\n{checks.stdout.strip()}\n```")
        elif checks.returncode != 0 and checks.stdout.strip():
            sections.append(f"### CI Checks (failing)\n```\n{checks.stdout.strip()}\n```")

        # Review comments
        comments = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                pr_url,
                "--json",
                "comments,reviews",
                "--repo",
                self.repo,
            ],
            capture_output=True,
            text=True,
        )
        if comments.returncode == 0:
            data = json.loads(comments.stdout)
            review_bodies: list[str] = []
            for review in data.get("reviews", []):
                body = str(review.get("body", "")).strip()
                state = str(review.get("state", ""))
                if body:
                    review_bodies.append(f"**{state}:** {body}")
            for comment in data.get("comments", []):
                body = str(comment.get("body", "")).strip()
                author = str(comment.get("author", {}).get("login", ""))
                if body and not body.startswith("<!--"):
                    review_bodies.append(f"**{author}:** {body}")
            if review_bodies:
                sections.append("### PR Comments\n" + "\n\n".join(review_bodies))

        return "\n\n".join(sections)

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
            return
        if self._probe is not None:
            self._probe.pr_marked_ready(pr_url=pr_url)

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

        return True  # Optimistic: let merge() handle the actual failure

    def merge(self, pr_url: str, task_id: str, spec_ref: str) -> bool:
        """Squash-merge a PR, preserving trailers. Returns True on success.

        If merge conflict, returns False (caller handles conflict internally).
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

        return result.returncode == 0

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
                    return False

                # Remove stale verdict file if present (secondary cleanup)
                _remove_verdict_file(tmpdir)

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
                        return False

                if self._probe is not None:
                    self._probe.branch_pushed(branch=branch)
                return True
            finally:
                # Clean up the worktree
                subprocess.run(
                    ["git", "worktree", "remove", "--force", tmpdir],
                    capture_output=True,
                    text=True,
                )


def _remove_verdict_file(tmpdir: str) -> None:
    """Remove .hyperloop/worker-result.yaml from a worktree if present.

    Best-effort — if the file doesn't exist or removal fails, silently
    continues. The commit is only created if the file was actually removed.
    """
    from hyperloop.adapters.verdict import VERDICT_FILE

    verdict_path = os.path.join(tmpdir, VERDICT_FILE)
    if not os.path.isfile(verdict_path):
        return

    subprocess.run(
        ["git", "-C", tmpdir, "rm", "-f", VERDICT_FILE],
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            tmpdir,
            "commit",
            "-m",
            "orchestrator: clean worker verdict",
        ],
        capture_output=True,
        env={**os.environ, "GIT_EDITOR": "true"},
    )


def _pr_body(
    task_id: str,
    spec_ref: str,
    has_gate: bool,
    description: str | None = None,
) -> str:
    """Generate the PR description body."""
    lines: list[str] = []

    if description:
        lines.extend([description, "", "---", ""])

    lines.extend(
        [
            f"**Task:** `{task_id}`",
            f"**Spec:** `{spec_ref}`",
            "",
        ]
    )

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
            "",
            "---",
            "",
            "This PR was created by [hyperloop](https://github.com/jsell-rh/hyperloop),",
            "an AI agent orchestrator.",
        ]
    )

    return "\n".join(lines)


def _is_auto_resolvable(path: str) -> bool:
    """Check if a conflicting file can be auto-resolved."""
    from hyperloop.adapters.verdict import VERDICT_FILE

    return path.startswith(".hyperloop/state/") or path == VERDICT_FILE


def _resolve_rebase_state_conflicts(tmpdir: str) -> bool:
    """Auto-resolve .hyperloop/state/ and verdict file conflicts during rebase.

    State file ownership:
      - tasks/   → take ours (main/trunk, the rebase target)
      - reviews/ → take theirs (worker commit being replayed)
      - worker-result.yaml → delete (should never exist on trunk)

    If non-resolvable conflicts exist, returns False (caller should abort).
    May loop through multiple conflicting commits (rebase --continue
    can hit the next conflict).
    """
    from hyperloop.adapters.verdict import VERDICT_FILE

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

        non_resolvable = [f for f in conflicted if not _is_auto_resolvable(f)]
        if non_resolvable:
            return False  # Real conflicts — caller should abort

        # Resolve each file
        for f in conflicted:
            if f == VERDICT_FILE:
                # Verdict file should never be on trunk — delete it
                subprocess.run(
                    ["git", "-C", tmpdir, "rm", "-f", "--", f],
                    capture_output=True,
                )
            elif f.startswith(".hyperloop/state/tasks/"):
                # Orchestrator owns task files — take trunk version
                subprocess.run(
                    ["git", "-C", tmpdir, "checkout", "--ours", "--", f],
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "-C", tmpdir, "add", f],
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
            env={**os.environ, "GIT_EDITOR": "true"},
        )
        if cont.returncode == 0:
            return True  # Rebase completed successfully

    return False  # Exceeded max rounds


def _conventional_title(title: str, spec_ref: str) -> str:
    """Derive a conventional commit-style PR title from a task title and spec_ref.

    'specs/iam/tenants.spec.md@abc' + 'Implement tenant CRUD' -> 'feat(iam): implement tenant CRUD'
    'specs/widget.spec.md' + 'Build widget' -> 'feat: build widget'
    """
    name = spec_ref.split("@")[0] if "@" in spec_ref else spec_ref
    name = re.sub(r"^specs/", "", name)
    name = re.sub(r"\.spec\.md$|\.md$", "", name)

    # Use the directory as scope, or no scope for top-level specs
    parts = name.split("/")
    scope = parts[0] if len(parts) > 1 else ""

    # Lowercase the first letter of the title for conventional commit style
    clean_title = title[0].lower() + title[1:] if title else title
    # Strip trailing period
    clean_title = clean_title.rstrip(".")

    if scope:
        return f"feat({scope}): {clean_title}"
    return f"feat: {clean_title}"


def _spec_name_from_ref(spec_ref: str) -> str:
    """Derive a spec label name from a spec_ref path.

    'specs/persistence.md' -> 'persistence'
    'specs/persistence.md@abc123' -> 'persistence'
    'specs/sub/feature.md' -> 'sub/feature'
    """
    name = spec_ref.split("@")[0] if "@" in spec_ref else spec_ref
    name = re.sub(r"^specs/", "", name)
    name = re.sub(r"\.md$", "", name)
    return name
