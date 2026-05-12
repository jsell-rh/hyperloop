from __future__ import annotations

import subprocess
from pathlib import Path

from hyperloop.reconciliation.models.spec_entry import SpecEntry


class GitSpecSource:
    def __init__(
        self,
        repo_path: Path,
        *,
        specs_dir: str = "specs",
        spec_suffix: str = ".spec.md",
        remote: str = "origin",
    ) -> None:
        self._repo_path = repo_path
        self._specs_dir = specs_dir
        self._spec_suffix = spec_suffix
        self._remote = remote

    def list_specs(self) -> list[SpecEntry]:
        result = self._git("ls-tree", "-r", "HEAD", "--", self._specs_dir, check=False)
        if result.returncode != 0:
            return []

        entries: list[SpecEntry] = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t", maxsplit=1)
            if len(parts) != 2:
                continue
            meta, path = parts
            if not path.endswith(self._spec_suffix):
                continue
            blob_sha = meta.split()[2]
            entries.append(SpecEntry(path=path, blob_sha=blob_sha))
        return entries

    def read_at(self, path: str, blob_sha: str) -> str:
        result = self._git("cat-file", "blob", blob_sha)
        return result.stdout

    def diff(self, path: str, old_sha: str | None, new_sha: str) -> str:
        if old_sha is None:
            return self.read_at(path, new_sha)

        result = self._git("diff", old_sha, new_sha)
        return result.stdout

    def sync(self) -> None:
        self._git("fetch", self._remote, check=False)
        remote_ref = f"{self._remote}/HEAD"
        result = self._git("rev-parse", "--verify", remote_ref, check=False)
        if result.returncode != 0:
            result = self._git(
                "symbolic-ref", f"refs/remotes/{self._remote}/HEAD", check=False
            )
            if result.returncode != 0:
                default_branch = self._detect_default_branch()
                remote_ref = f"{self._remote}/{default_branch}"

        self._git("merge", "--ff-only", remote_ref, check=False)

    def _detect_default_branch(self) -> str:
        result = self._git("branch", "-r", "--list", f"{self._remote}/*", check=False)
        for line in result.stdout.strip().splitlines():
            branch = line.strip()
            if "->" in branch:
                continue
            name = branch.split("/", maxsplit=1)[1]
            if name in ("main", "master"):
                return name
        return "main"

    def _git(
        self,
        *args: str,
        input: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self._repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            input=input,
            check=check,
        )
