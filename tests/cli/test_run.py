from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from hyperloop.cli.app import cli
from hyperloop.reconciliation.models.configuration import Configuration


class FakeReconciler:
    def __init__(self) -> None:
        self.started = False
        self.config: Configuration | None = None

    def run(self, config: Configuration) -> None:
        self.started = True
        self.config = config


class TestRunCommand:
    def test_run_starts_reconciler(self) -> None:
        reconciler = FakeReconciler()
        runner = CliRunner()
        result = runner.invoke(cli, ["run"], obj=reconciler)
        assert result.exit_code == 0
        assert reconciler.started is True

    def test_run_loads_default_config(self) -> None:
        reconciler = FakeReconciler()
        runner = CliRunner()
        result = runner.invoke(cli, ["run"], obj=reconciler)
        assert result.exit_code == 0
        assert reconciler.config is not None
        assert reconciler.config.convergence_bound == 3

    def test_run_loads_config_from_file(self, tmp_path: Path) -> None:
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text(
            f"convergence_bound: 7\nspecs_directory: '{specs_dir}'\n"
        )
        reconciler = FakeReconciler()
        runner = CliRunner()
        result = runner.invoke(
            cli, ["run", "--config", str(config_file)], obj=reconciler
        )
        assert result.exit_code == 0
        assert reconciler.config is not None
        assert reconciler.config.convergence_bound == 7

    def test_run_fails_on_invalid_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text("convergence_bound: -1\n")
        reconciler = FakeReconciler()
        runner = CliRunner()
        result = runner.invoke(
            cli, ["run", "--config", str(config_file)], obj=reconciler
        )
        assert result.exit_code != 0
        assert reconciler.started is False

    def test_run_with_nonexistent_config_uses_defaults(self) -> None:
        reconciler = FakeReconciler()
        runner = CliRunner()
        result = runner.invoke(
            cli, ["run", "--config", "/nonexistent/.hyperloop.yaml"], obj=reconciler
        )
        assert result.exit_code == 0
        assert reconciler.config is not None
        assert reconciler.config.convergence_bound == 3

    def test_run_without_reconciler_errors(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["run"], obj=object())
        assert result.exit_code != 0
        assert "not yet implemented" in result.output
