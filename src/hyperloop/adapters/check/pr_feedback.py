"""PRFeedbackCheck — passes if all PR comments predate the latest push."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from hyperloop.domain.model import Task


class PRFeedbackCheck:
    """CheckPort adapter for pr-feedback-addressed.

    Compares the timestamp of the latest push to the branch against
    the timestamps of PR review comments. If any comment is newer
    than the latest push, the check fails (unaddressed feedback).
    """

    def __init__(self, repo: str) -> None:
        self._repo = repo

    def evaluate(self, task: Task, check_name: str, args: dict[str, object]) -> bool:
        """Evaluate the check. Returns True if all feedback is addressed."""
        if check_name != "pr-feedback-addressed":
            return True

        if task.pr is None:
            return True

        raw_reviewers = args.get("require_reviewers")
        if isinstance(raw_reviewers, list):
            reviewer_list = cast("list[str]", raw_reviewers)
            if not self._all_reviewers_posted(task.pr, reviewer_list):
                return False

        latest_push = self._get_latest_push_time(task.pr)
        if latest_push is None:
            return True

        latest_comment = self._get_latest_comment_time(task.pr)
        if latest_comment is None:
            return True

        return latest_push >= latest_comment

    def _all_reviewers_posted(self, pr_url: str, required: list[str]) -> bool:
        """Return True if every required reviewer has posted at least one review or comment."""
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                pr_url,
                "--json",
                "comments,reviews",
                "--repo",
                self._repo,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False

        data = json.loads(result.stdout)
        posted: set[str] = set()

        for review in data.get("reviews", []):
            author = review.get("author", {}).get("login", "")
            if author:
                posted.add(author)

        for comment in data.get("comments", []):
            author = comment.get("author", {}).get("login", "")
            if author:
                posted.add(author)

        return all(r in posted for r in required)

    def _get_latest_push_time(self, pr_url: str) -> datetime | None:
        """Get the timestamp of the latest commit on the PR branch."""
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                pr_url,
                "--json",
                "commits",
                "--repo",
                self._repo,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        commits = data.get("commits", [])
        if not commits:
            return None

        latest = commits[-1]
        date_str = latest.get("committedDate", "")
        if not date_str:
            return None
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))

    def _get_latest_comment_time(self, pr_url: str) -> datetime | None:
        """Get the timestamp of the most recent review comment or review."""
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                pr_url,
                "--json",
                "comments,reviews",
                "--repo",
                self._repo,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        timestamps: list[datetime] = []

        for review in data.get("reviews", []):
            submitted = review.get("submittedAt", "")
            if submitted:
                timestamps.append(datetime.fromisoformat(submitted.replace("Z", "+00:00")))

        for comment in data.get("comments", []):
            created = comment.get("createdAt", "")
            body = str(comment.get("body", ""))
            # Skip bot comments (hyperloop's own)
            if body.startswith("<!--") or not body.strip():
                continue
            if created:
                timestamps.append(datetime.fromisoformat(created.replace("Z", "+00:00")))

        if not timestamps:
            return None
        return max(timestamps)
