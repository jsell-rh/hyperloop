"""GitSpecSource — reads spec files from a git repository."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from hyperloop.ports.spec_source import SpecChange

if TYPE_CHECKING:
    from pathlib import Path


class GitSpecSource:
    """SpecSource backed by git — uses HEAD SHA as version marker."""

    def __init__(self, repo_path: Path) -> None:
        self._repo = repo_path

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self._repo), *args],
            capture_output=True,
            text=True,
        )

    def detect_changes(self, since: str | None) -> list[SpecChange]:
        if since is None:
            result = self._git("ls-files", "specs/*.md")
            if result.returncode != 0:
                return []
            return [
                SpecChange(path=p.strip(), change_type="added")
                for p in result.stdout.strip().splitlines()
                if p.strip()
            ]

        result = self._git("diff", "--name-status", since, "HEAD", "--", "specs/*.md")
        if result.returncode != 0:
            return []

        changes: list[SpecChange] = []
        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            status, path = parts
            change_type = {"A": "added", "M": "modified", "D": "deleted"}.get(status[0], "modified")
            changes.append(SpecChange(path=path, change_type=change_type))
        return changes

    def read(self, spec_ref: str) -> str:
        if "@" in spec_ref:
            path, sha = spec_ref.rsplit("@", 1)
            result = self._git("show", f"{sha}:{path}")
        else:
            result = self._git("show", f"HEAD:{spec_ref}")
        if result.returncode != 0:
            return ""
        return result.stdout

    def current_version(self) -> str:
        result = self._git("rev-parse", "HEAD")
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
