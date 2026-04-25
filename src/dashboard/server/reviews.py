"""Review file parser for task detail endpoint."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

import yaml

from dashboard.server.models import Review

if TYPE_CHECKING:
    from hyperloop.ports.state import StateStore


def read_reviews(store: StateStore, task_id: str) -> list[Review]:
    """Read all review files for a task from the state store.

    Uses ``StateStore.list_review_contents`` to read review files.
    Each file has YAML frontmatter containing round, role, and verdict
    metadata. The body after the frontmatter is the review detail text.
    """
    contents = store.list_review_contents(task_id)

    results: list[Review] = []
    for content in contents:
        match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
        if not match:
            continue
        try:
            fm = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            continue
        if not isinstance(fm, dict):
            continue
        fm_dict = cast("dict[str, object]", fm)
        body = match.group(2).strip()
        round_val = fm_dict.get("round", 0)
        results.append(
            Review(
                round=int(round_val) if isinstance(round_val, (int, str, float)) else 0,
                role=str(fm_dict.get("role", "")),
                verdict=str(fm_dict.get("verdict", "")),
                detail=body,
            )
        )
    return results
