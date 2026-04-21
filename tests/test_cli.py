"""Tests for CLI entry point — TDD, written before implementation."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

from hyperloop.cli import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes so assertions match regardless of color env."""
    return _ANSI_RE.sub("", text)


class TestHelpCommand:
    """CLI --help shows useful output."""

    def test_help_exits_zero(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_help_shows_app_name(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert "hyperloop" in result.output.lower() or "orchestrat" in result.output.lower()

    def test_run_help_shows_options(self) -> None:
        result = runner.invoke(app, ["run", "--help"])
        output = _strip_ansi(result.output)
        assert result.exit_code == 0
        assert "--repo" in output
        assert "--dry-run" in output
        assert "--config" in output


class TestDryRun:
    """--dry-run shows config without executing."""

    def test_dry_run_shows_config_table(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text(
            """\
repo: acme/widgets
base_branch: main
"""
        )

        result = runner.invoke(app, ["run", "--dry-run", "--config", str(config_file)])

        assert result.exit_code == 0
        assert "acme/widgets" in result.output
        assert "dry" in result.output.lower() or "Dry" in result.output

    def test_dry_run_with_cli_overrides(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text("repo: acme/widgets\n")

        result = runner.invoke(
            app,
            [
                "run",
                "--dry-run",
                "--config",
                str(config_file),
                "--repo",
                "other/repo",
                "--branch",
                "develop",
            ],
        )

        assert result.exit_code == 0
        assert "other/repo" in result.output
        assert "develop" in result.output

    def test_dry_run_all_defaults(self) -> None:
        result = runner.invoke(app, ["run", "--dry-run"])

        assert result.exit_code == 0
        assert "main" in result.output


class TestRunRequiresRepo:
    """Running without --dry-run and without a repo should show an error."""

    def test_no_repo_shows_error(self, tmp_path: Path) -> None:
        # Point --path at a non-git temp dir so the CLI never touches the real repo
        result = runner.invoke(
            app,
            ["run", "--path", str(tmp_path), "--config", str(tmp_path / "nope.yaml")],
        )

        # Should exit non-zero — tmp_path is not a git repository
        assert result.exit_code != 0
