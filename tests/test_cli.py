"""Tests for CLI entry point — TDD, written before implementation."""

from __future__ import annotations

from typer.testing import CliRunner

from k_orchestrate.cli import app

runner = CliRunner()


class TestHelpCommand:
    """CLI --help shows useful output."""

    def test_help_exits_zero(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_help_shows_app_name(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert "k-orchestrate" in result.output.lower() or "orchestrat" in result.output.lower()

    def test_run_help_shows_options(self) -> None:
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--repo" in result.output
        assert "--dry-run" in result.output
        assert "--config" in result.output


class TestDryRun:
    """--dry-run shows config without executing."""

    def test_dry_run_shows_config_table(self, tmp_path) -> None:
        config_file = tmp_path / ".k-orchestrate.yaml"
        config_file.write_text(
            """\
target:
  repo: acme/widgets
  base_branch: main
"""
        )

        result = runner.invoke(app, ["run", "--dry-run", "--config", str(config_file)])

        assert result.exit_code == 0
        assert "acme/widgets" in result.output
        assert "dry" in result.output.lower() or "Dry" in result.output

    def test_dry_run_with_cli_overrides(self, tmp_path) -> None:
        config_file = tmp_path / ".k-orchestrate.yaml"
        config_file.write_text("target:\n  repo: acme/widgets\n")

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
        assert "local" in result.output


class TestRunRequiresRepo:
    """Running without --dry-run and without a repo should show an error."""

    def test_no_repo_shows_error(self, tmp_path) -> None:
        # No config file, no --repo flag, no git remote to infer from
        result = runner.invoke(app, ["run", "--config", str(tmp_path / "nope.yaml")])

        # Should exit non-zero or show an error message
        assert result.exit_code != 0 or "repo" in result.output.lower()
