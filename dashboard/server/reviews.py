"""Review file parser for task detail endpoint."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path

from dashboard.server.models import Review


def read_reviews(repo_path: Path, task_id: str) -> list[Review]:
    """Read all review files for a task and return structured Review objects.

    Review files live at ``.hyperloop/state/reviews/{task_id}-round-{n}.md``
    with YAML frontmatter containing round, role, and verdict metadata.
    The body after the frontmatter is the review detail text.
    """
    reviews_dir = repo_path / ".hyperloop" / "state" / "reviews"
    if not reviews_dir.exists():
        return []

    results: list[Review] = []
    pattern = f"{task_id}-round-*.md"
    for review_file in sorted(reviews_dir.glob(pattern)):
        content = review_file.read_text()
        match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
        if not match:
            continue
        try:
            fm = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            continue
        if not isinstance(fm, dict):
            continue
        body = match.group(2).strip()
        results.append(
            Review(
                round=int(fm.get("round", 0)),
                role=str(fm.get("role", "")),
                verdict=str(fm.get("verdict", "")),
                detail=body,
            )
        )
    return results
