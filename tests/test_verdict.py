"""Tests for verdict file parsing and cleanup."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from hyperloop.adapters.verdict import (
    VERDICT_FILE,
    _parse_verdict,
    read_verdict_file,
    read_verdict_from_ref,
)
from hyperloop.domain.model import Verdict

if TYPE_CHECKING:
    from pathlib import Path


class TestParseVerdict:
    """_parse_verdict extracts verdict and detail from YAML frontmatter."""

    def test_parses_pass(self) -> None:
        content = "---\nverdict: pass\n---\nAll tests pass.\n"
        result = _parse_verdict(content)
        assert result is not None
        assert result.verdict == Verdict.PASS
        assert result.detail == "All tests pass."

    def test_parses_fail(self) -> None:
        content = "---\nverdict: fail\n---\nThree issues found.\n"
        result = _parse_verdict(content)
        assert result is not None
        assert result.verdict == Verdict.FAIL
        assert result.detail == "Three issues found."

    def test_returns_none_on_missing_frontmatter(self) -> None:
        assert _parse_verdict("No frontmatter here.\n") is None

    def test_returns_none_on_invalid_verdict_value(self) -> None:
        assert _parse_verdict("---\nverdict: maybe\n---\nBody.\n") is None

    def test_returns_none_on_malformed_yaml(self) -> None:
        assert _parse_verdict("---\n: broken {{{\n---\nBody.\n") is None

    def test_returns_none_on_non_dict_frontmatter(self) -> None:
        assert _parse_verdict("---\n- item\n---\nBody.\n") is None

    def test_strips_body_whitespace(self) -> None:
        content = "---\nverdict: pass\n---\n\n  Detail with space.  \n\n"
        result = _parse_verdict(content)
        assert result is not None
        assert result.detail == "Detail with space."

    def test_multiline_detail(self) -> None:
        content = "---\nverdict: fail\n---\nLine 1.\nLine 2.\nLine 3.\n"
        result = _parse_verdict(content)
        assert result is not None
        assert result.detail == "Line 1.\nLine 2.\nLine 3."


class TestReadVerdictFile:
    """read_verdict_file reads from a worktree filesystem path."""

    def test_reads_existing_file(self, tmp_path: Path) -> None:
        verdict_dir = tmp_path / ".hyperloop"
        verdict_dir.mkdir()
        (verdict_dir / "worker-result.yaml").write_text("---\nverdict: pass\n---\nAll good.\n")
        result = read_verdict_file(str(tmp_path))
        assert result is not None
        assert result.verdict == Verdict.PASS
        assert result.detail == "All good."

    def test_returns_none_when_missing(self, tmp_path: Path) -> None:
        assert read_verdict_file(str(tmp_path)) is None


class TestReadVerdictFromRef:
    """read_verdict_from_ref reads from a git ref."""

    def test_reads_from_branch_ref(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        subprocess.run(
            ["git", "init", "-b", "main", str(repo)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
            check=True,
            capture_output=True,
            env=env,
        )
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-b", "work"],
            check=True,
            capture_output=True,
        )
        verdict_dir = repo / ".hyperloop"
        verdict_dir.mkdir()
        (verdict_dir / "worker-result.yaml").write_text("---\nverdict: fail\n---\nTwo issues.\n")
        subprocess.run(
            ["git", "-C", str(repo), "add", "."],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "verdict"],
            check=True,
            capture_output=True,
            env=env,
        )

        result = read_verdict_from_ref(str(repo), "work")
        assert result is not None
        assert result.verdict == Verdict.FAIL
        assert result.detail == "Two issues."

    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        subprocess.run(
            ["git", "init", "-b", "main", str(repo)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
            check=True,
            capture_output=True,
            env=env,
        )
        assert read_verdict_from_ref(str(repo), "main") is None


class TestVerdictFilePath:
    """VERDICT_FILE constant matches what agents are told to write."""

    def test_path(self) -> None:
        assert VERDICT_FILE == ".hyperloop/worker-result.yaml"
