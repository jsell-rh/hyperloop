"""GitHubFeedbackAdapter — FeedbackPort implementation using gh CLI."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from typing import TYPE_CHECKING, cast

from hyperloop.domain.model import PRComment

if TYPE_CHECKING:
    from hyperloop.domain.model import Task

_log = logging.getLogger(__name__)

_PR_URL_RE = re.compile(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)")


def _parse_pr_url(pr_url: str) -> tuple[str, str, str] | None:
    """Extract (owner, repo, number) from a GitHub PR URL."""
    m = _PR_URL_RE.match(pr_url)
    if m is None:
        return None
    return m.group(1), m.group(2), m.group(3)


class GitHubFeedbackAdapter:
    """FeedbackPort implementation that uses gh CLI to fetch and mark PR comments."""

    def __init__(self, repo: str) -> None:
        self._repo = repo

    def get_unprocessed(
        self, task: Task, allowed_authors: list[str], processed_emoji: str
    ) -> list[PRComment]:
        if task.pr is None:
            return []

        parsed = _parse_pr_url(task.pr)
        if parsed is None:
            _log.warning("Cannot parse PR URL: %s", task.pr)
            return []

        owner, repo, number = parsed
        allowed_set = set(allowed_authors)

        issue_comments = self._fetch_issue_comments(owner, repo, number)
        review_comments = self._fetch_review_comments(owner, repo, number)

        result: list[PRComment] = []

        for comment in issue_comments:
            user_obj = comment.get("user")
            user = cast("dict[str, object]", user_obj) if isinstance(user_obj, dict) else {}
            author = str(user.get("login", ""))
            if author not in allowed_set:
                continue
            comment_id = str(comment.get("id", ""))
            if self._has_reaction(owner, repo, comment_id, processed_emoji, kind="issues"):
                continue
            result.append(
                PRComment(
                    id=comment_id,
                    author=author,
                    body=str(comment.get("body", "")),
                    url=str(comment.get("html_url", "")),
                )
            )

        for comment in review_comments:
            user_obj = comment.get("user")
            user = cast("dict[str, object]", user_obj) if isinstance(user_obj, dict) else {}
            author = str(user.get("login", ""))
            if author not in allowed_set:
                continue
            comment_id = str(comment.get("id", ""))
            if self._has_reaction(owner, repo, comment_id, processed_emoji, kind="pulls"):
                continue
            result.append(
                PRComment(
                    id=comment_id,
                    author=author,
                    body=str(comment.get("body", "")),
                    url=str(comment.get("html_url", "")),
                )
            )

        return result

    def mark_processed(self, task: Task, comment_ids: list[str], emoji: str) -> None:
        if task.pr is None:
            return

        parsed = _parse_pr_url(task.pr)
        if parsed is None:
            return

        owner, repo, _number = parsed

        for comment_id in comment_ids:
            self._add_reaction_issues(owner, repo, comment_id, emoji)
            self._add_reaction_pulls(owner, repo, comment_id, emoji)

    def _fetch_issue_comments(self, owner: str, repo: str, number: str) -> list[dict[str, object]]:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{owner}/{repo}/issues/{number}/comments",
                "--paginate",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            _log.warning("Failed to fetch issue comments: %s", result.stderr)
            return []
        try:
            data: object = json.loads(result.stdout)
            if isinstance(data, list):
                return cast("list[dict[str, object]]", data)
            return []
        except json.JSONDecodeError:
            return []

    def _fetch_review_comments(self, owner: str, repo: str, number: str) -> list[dict[str, object]]:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{owner}/{repo}/pulls/{number}/comments",
                "--paginate",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            _log.warning("Failed to fetch review comments: %s", result.stderr)
            return []
        try:
            data: object = json.loads(result.stdout)
            if isinstance(data, list):
                return cast("list[dict[str, object]]", data)
            return []
        except json.JSONDecodeError:
            return []

    def _has_reaction(
        self,
        owner: str,
        repo: str,
        comment_id: str,
        emoji: str,
        kind: str,
    ) -> bool:
        endpoint = (
            f"repos/{owner}/{repo}/issues/comments/{comment_id}/reactions"
            if kind == "issues"
            else f"repos/{owner}/{repo}/pulls/comments/{comment_id}/reactions"
        )
        result = subprocess.run(
            ["gh", "api", endpoint, "--paginate"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False
        try:
            raw: object = json.loads(result.stdout)
            if not isinstance(raw, list):
                return False
            reactions = cast("list[dict[str, object]]", raw)
            return any(r.get("content") == emoji for r in reactions)
        except json.JSONDecodeError:
            return False

    def _add_reaction_issues(self, owner: str, repo: str, comment_id: str, emoji: str) -> None:
        subprocess.run(
            [
                "gh",
                "api",
                f"repos/{owner}/{repo}/issues/comments/{comment_id}/reactions",
                "-f",
                f"content={emoji}",
            ],
            capture_output=True,
            text=True,
        )

    def _add_reaction_pulls(self, owner: str, repo: str, comment_id: str, emoji: str) -> None:
        subprocess.run(
            [
                "gh",
                "api",
                f"repos/{owner}/{repo}/pulls/comments/{comment_id}/reactions",
                "-f",
                f"content={emoji}",
            ],
            capture_output=True,
            text=True,
        )
