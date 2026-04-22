"""Verdict file — runtime-agnostic worker result transport.

Workers write their verdict to ``.hyperloop/worker-result.yaml`` on their
branch.  The orchestrator reads it during reap, then removes it from the
branch to prevent it from leaking to trunk via squash merge.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import cast

import yaml

from hyperloop.domain.model import Verdict, WorkerResult

VERDICT_FILE = ".hyperloop/worker-result.yaml"


def read_verdict_file(worktree_path: str) -> WorkerResult | None:
    """Read and parse the verdict file from a worktree filesystem path.

    Returns None if the file doesn't exist or can't be parsed.
    """
    path = os.path.join(worktree_path, VERDICT_FILE)
    if not os.path.isfile(path):
        return None

    try:
        with open(path) as f:
            content = f.read()
        return _parse_verdict(content)
    except Exception:
        return None


def read_verdict_from_ref(repo_path: str, ref: str) -> WorkerResult | None:
    """Read and parse the verdict file from a git ref (e.g. origin/branch).

    Used by the Ambient runtime which has no local worktree access.
    Returns None if the file doesn't exist or can't be parsed.
    """
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "show", f"{ref}:{VERDICT_FILE}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return None

    return _parse_verdict(result.stdout)


def _parse_verdict(content: str) -> WorkerResult | None:
    """Parse YAML frontmatter + body from verdict file content."""
    match = re.match(r"^---\n(.*?\n)---\n(.*)", content, re.DOTALL)
    if match is None:
        return None

    try:
        fm_raw = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None

    if not isinstance(fm_raw, dict):
        return None

    fm = cast("dict[str, object]", fm_raw)
    verdict_str = str(fm.get("verdict", ""))
    if verdict_str not in ("pass", "fail"):
        return None

    body = match.group(2).strip()
    return WorkerResult(
        verdict=Verdict(verdict_str),
        detail=body,
    )
