"""GitSpecSource — reads spec files from a git repository."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from hyperloop.domain.model import SpecChangeType
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
                SpecChange(path=p.strip(), change_type=SpecChangeType.ADDED)
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
            _CHANGE_MAP = {
                "A": SpecChangeType.ADDED,
                "M": SpecChangeType.MODIFIED,
                "D": SpecChangeType.DELETED,
            }
            change_type = _CHANGE_MAP.get(status[0], SpecChangeType.MODIFIED)
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

    def file_version(self, spec_path: str) -> str:
        result = self._git("rev-parse", f"HEAD:{spec_path}")
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    def file_version_at(self, spec_path: str, ref: str) -> str:
        """Resolve a ref (commit or blob SHA) to the blob SHA for a file.

        If ref is already a blob SHA, returns it unchanged. If ref is a commit,
        returns the blob SHA of spec_path at that commit.
        """
        obj_type = self._git("cat-file", "-t", ref)
        if obj_type.returncode != 0:
            return ref
        kind = obj_type.stdout.strip()
        if kind == "blob":
            return ref
        if kind == "commit":
            result = self._git("rev-parse", f"{ref}:{spec_path}")
            if result.returncode != 0:
                return ref
            return result.stdout.strip()
        return ref

    def has_changed(self, spec_path: str, since_version: str) -> bool:
        result = self._git("diff", "--quiet", since_version, "HEAD", "--", spec_path)
        return result.returncode != 0

    def get_diff(self, spec_path: str, since_version: str) -> str:
        result = self._git("diff", since_version, "HEAD", "--", spec_path)
        if result.returncode != 0:
            return ""
        return result.stdout
