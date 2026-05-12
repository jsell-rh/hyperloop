from __future__ import annotations

import subprocess
from pathlib import Path

from hyperloop.reconciliation.adapters.git_spec_source import GitSpecSource
from hyperloop.reconciliation.models.spec_entry import SpecEntry


def _git(
    repo: Path, *args: str, input: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        input=input,
        check=True,
    )


def _write_and_commit(repo: Path, path: str, content: str, message: str) -> str:
    full_path = repo / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)
    _git(repo, "add", path)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _make_source(repo_path: Path) -> GitSpecSource:
    return GitSpecSource(repo_path, specs_dir="specs", remote="origin")


class TestListSpecs:
    def test_returns_empty_when_no_specs(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        source = _make_source(local)
        assert source.list_specs() == []

    def test_returns_spec_files_with_blob_shas(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        _write_and_commit(local, "specs/auth.spec.md", "# Auth Spec\n", "Add auth spec")
        source = _make_source(local)

        entries = source.list_specs()
        assert len(entries) == 1
        assert entries[0].path == "specs/auth.spec.md"
        assert len(entries[0].blob_sha) == 40

    def test_blob_sha_matches_git_content_hash(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        content = "# Auth Spec\n"
        _write_and_commit(local, "specs/auth.spec.md", content, "Add auth spec")
        source = _make_source(local)

        entries = source.list_specs()
        expected_sha = _git(
            local, "hash-object", "--stdin", input=content
        ).stdout.strip()
        assert entries[0].blob_sha == expected_sha

    def test_returns_multiple_specs(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _write_and_commit(local, "specs/auth.spec.md", "# Auth\n", "Add auth")
        _write_and_commit(local, "specs/users.spec.md", "# Users\n", "Add users")
        source = _make_source(local)

        entries = source.list_specs()
        paths = {e.path for e in entries}
        assert paths == {"specs/auth.spec.md", "specs/users.spec.md"}

    def test_returns_specs_in_nested_dirs(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _write_and_commit(
            local,
            "specs/reconciliation/ports.spec.md",
            "# Ports\n",
            "Add ports spec",
        )
        source = _make_source(local)

        entries = source.list_specs()
        assert len(entries) == 1
        assert entries[0].path == "specs/reconciliation/ports.spec.md"

    def test_ignores_non_spec_files(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _write_and_commit(local, "specs/auth.spec.md", "# Auth\n", "Add auth")
        _write_and_commit(local, "specs/README.md", "# Readme\n", "Add readme")
        _write_and_commit(local, "specs/notes.txt", "notes\n", "Add notes")
        source = _make_source(local)

        entries = source.list_specs()
        assert len(entries) == 1
        assert entries[0].path == "specs/auth.spec.md"

    def test_returns_spec_entry_instances(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _write_and_commit(local, "specs/auth.spec.md", "# Auth\n", "Add auth")
        source = _make_source(local)

        entries = source.list_specs()
        assert all(isinstance(e, SpecEntry) for e in entries)


class TestReadAt:
    def test_returns_content_at_pinned_blob_sha(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        original = "# Auth Spec v1\n"
        _write_and_commit(local, "specs/auth.spec.md", original, "Add auth v1")
        source = _make_source(local)
        original_sha = source.list_specs()[0].blob_sha

        _write_and_commit(local, "specs/auth.spec.md", "# Auth Spec v2\n", "Update v2")

        content = source.read_at("specs/auth.spec.md", original_sha)
        assert content == original

    def test_does_not_return_current_version(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _write_and_commit(local, "specs/auth.spec.md", "# v1\n", "v1")
        source = _make_source(local)
        v1_sha = source.list_specs()[0].blob_sha

        updated = "# v2\n"
        _write_and_commit(local, "specs/auth.spec.md", updated, "v2")

        content = source.read_at("specs/auth.spec.md", v1_sha)
        assert content != updated


class TestDiff:
    def test_returns_textual_diff_between_versions(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        _write_and_commit(
            local, "specs/auth.spec.md", "# Auth v1\nLogin required\n", "v1"
        )
        source = _make_source(local)
        v1_sha = source.list_specs()[0].blob_sha

        _write_and_commit(
            local,
            "specs/auth.spec.md",
            "# Auth v2\nLogin required\nMFA added\n",
            "v2",
        )
        v2_sha = source.list_specs()[0].blob_sha

        diff_text = source.diff("specs/auth.spec.md", v1_sha, v2_sha)
        assert "Auth v1" in diff_text
        assert "Auth v2" in diff_text
        assert "MFA added" in diff_text

    def test_returns_full_content_for_new_spec(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        content = "# Users Spec\nUser management\n"
        _write_and_commit(local, "specs/users.spec.md", content, "Add users")
        source = _make_source(local)
        sha = source.list_specs()[0].blob_sha

        diff_text = source.diff("specs/users.spec.md", None, sha)
        assert "Users Spec" in diff_text
        assert "User management" in diff_text

    def test_diff_shows_removals(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _write_and_commit(local, "specs/auth.spec.md", "# Auth\nLine A\nLine B\n", "v1")
        source = _make_source(local)
        v1_sha = source.list_specs()[0].blob_sha

        _write_and_commit(local, "specs/auth.spec.md", "# Auth\nLine A\n", "v2")
        v2_sha = source.list_specs()[0].blob_sha

        diff_text = source.diff("specs/auth.spec.md", v1_sha, v2_sha)
        assert "Line B" in diff_text


class TestSync:
    def test_updates_local_view_from_upstream(
        self, git_env: tuple[Path, Path], tmp_path: Path
    ) -> None:
        local, remote = git_env

        other = tmp_path / "other"
        subprocess.run(
            ["git", "clone", str(remote), str(other)],
            check=True,
            capture_output=True,
        )
        _git(other, "config", "user.name", "Test User")
        _git(other, "config", "user.email", "test@example.com")
        _write_and_commit(other, "specs/auth.spec.md", "# Auth\n", "Add auth")
        _git(other, "push", "origin", "main")

        source = _make_source(local)
        assert source.list_specs() == []

        source.sync()

        entries = source.list_specs()
        assert len(entries) == 1
        assert entries[0].path == "specs/auth.spec.md"

    def test_sync_picks_up_modifications(
        self, git_env: tuple[Path, Path], tmp_path: Path
    ) -> None:
        local, remote = git_env
        _write_and_commit(local, "specs/auth.spec.md", "# v1\n", "v1")
        _git(local, "push", "origin", "main")
        source = _make_source(local)
        v1_sha = source.list_specs()[0].blob_sha

        other = tmp_path / "other"
        subprocess.run(
            ["git", "clone", str(remote), str(other)],
            check=True,
            capture_output=True,
        )
        _git(other, "config", "user.name", "Test User")
        _git(other, "config", "user.email", "test@example.com")
        _write_and_commit(other, "specs/auth.spec.md", "# v2\n", "v2")
        _git(other, "push", "origin", "main")

        source.sync()

        entries = source.list_specs()
        assert entries[0].blob_sha != v1_sha

    def test_synced_content_is_readable(
        self, git_env: tuple[Path, Path], tmp_path: Path
    ) -> None:
        local, remote = git_env
        expected_content = "# Auth Spec\nLogin required\n"

        other = tmp_path / "other"
        subprocess.run(
            ["git", "clone", str(remote), str(other)],
            check=True,
            capture_output=True,
        )
        _git(other, "config", "user.name", "Test User")
        _git(other, "config", "user.email", "test@example.com")
        _write_and_commit(other, "specs/auth.spec.md", expected_content, "Add auth")
        _git(other, "push", "origin", "main")

        source = _make_source(local)
        source.sync()

        entries = source.list_specs()
        content = source.read_at(entries[0].path, entries[0].blob_sha)
        assert content == expected_content


class TestCustomSuffix:
    def test_filters_by_configured_suffix(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        _write_and_commit(local, "specs/auth.spec.md", "# Auth\n", "Add spec")
        _write_and_commit(local, "specs/auth.req.md", "# Auth Req\n", "Add req")
        source = GitSpecSource(
            local, specs_dir="specs", spec_suffix=".req.md", remote="origin"
        )

        entries = source.list_specs()
        assert len(entries) == 1
        assert entries[0].path == "specs/auth.req.md"


class TestProtocolConformance:
    def test_has_list_specs_method(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitSpecSource.list_specs)
        assert hints["return"] == list[SpecEntry]

    def test_has_read_at_method(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitSpecSource.read_at)
        assert hints["path"] is str
        assert hints["blob_sha"] is str
        assert hints["return"] is str

    def test_has_diff_method(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitSpecSource.diff)
        assert hints["path"] is str
        assert hints["new_sha"] is str
        assert hints["return"] is str

    def test_has_sync_method(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitSpecSource.sync)
        assert hints["return"] is type(None)

    def test_adapter_imports_from_domain(self) -> None:
        import inspect

        import hyperloop.reconciliation.adapters.git_spec_source as module

        source = inspect.getsource(module)
        assert "hyperloop.reconciliation.models" in source
