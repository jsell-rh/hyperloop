"""PR manager — draft PR lifecycle: creation, labeling, gate polling, merge.

Uses the `gh` CLI for all GitHub operations. The interface is matched by
FakePRManager (tests/fakes/pr.py) for testing without a real GitHub repo.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess

logger = logging.getLogger(__name__)


class PRManager:
    """Manages draft PR lifecycle: creation, labeling, gate polling, merge."""

    def __init__(
        self,
        repo: str,
        merge_strategy: str = "squash",
        delete_branch: bool = True,
    ) -> None:
        self.repo = repo
        self.merge_strategy = merge_strategy
        self.delete_branch = delete_branch

    def create_draft(self, task_id: str, branch: str, title: str, spec_ref: str) -> str:
        """Create a draft PR. Returns PR URL. Adds spec/task labels."""
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
                "",
                "--repo",
                self.repo,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        pr_url = result.stdout.strip()

        spec_name = _spec_name_from_ref(spec_ref)
        subprocess.run(
            [
                "gh",
                "pr",
                "edit",
                pr_url,
                "--add-label",
                f"task/{task_id}",
                "--add-label",
                f"spec/{spec_name}",
                "--repo",
                self.repo,
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        logger.info("Created draft PR %s for task %s", pr_url, task_id)
        return pr_url

    def check_gate(self, pr_url: str, gate: str) -> bool:
        """Check if a gate signal is present. v1: checks for 'lgtm' label.

        Returns True if gate is cleared. Removes the label to prevent re-triggering.
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
            check=True,
        )
        data = json.loads(result.stdout)
        label_names = {label["name"] for label in data.get("labels", [])}

        if "lgtm" in label_names:
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
                check=True,
            )
            logger.info("Gate '%s' cleared for PR %s (lgtm label found and removed)", gate, pr_url)
            return True

        return False

    def mark_ready(self, pr_url: str) -> None:
        """Mark a draft PR as ready for review."""
        subprocess.run(
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
            check=True,
        )
        logger.info("Marked PR %s as ready for review", pr_url)

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
        """Rebase a branch onto base. Returns True if clean, False if conflicts."""
        # Checkout the branch
        checkout = subprocess.run(
            ["git", "checkout", branch],
            capture_output=True,
            text=True,
        )
        if checkout.returncode != 0:
            logger.warning("Failed to checkout branch %s: %s", branch, checkout.stderr.strip())
            return False

        # Attempt rebase
        rebase = subprocess.run(
            ["git", "rebase", base_branch],
            capture_output=True,
            text=True,
        )
        if rebase.returncode != 0:
            # Abort the rebase on conflict
            subprocess.run(
                ["git", "rebase", "--abort"],
                capture_output=True,
                text=True,
            )
            logger.warning("Rebase conflict on branch %s onto %s", branch, base_branch)
            return False

        logger.info("Rebased branch %s onto %s", branch, base_branch)
        return True


def _spec_name_from_ref(spec_ref: str) -> str:
    """Derive a spec label name from a spec_ref path.

    'specs/persistence.md' -> 'persistence'
    'specs/sub/feature.md' -> 'sub/feature'
    """
    name = spec_ref
    name = re.sub(r"^specs/", "", name)
    name = re.sub(r"\.md$", "", name)
    return name
